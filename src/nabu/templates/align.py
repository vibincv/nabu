"""Where a template's page sits on this document (FR-5.2, M3 fix 2026-10-14).

A scan or phone photo of the same form is framed differently each time: moved, and zoomed in or
out. Each anchor of the template (a printed label, or a landmark: fixed printed text that is not
a value) is looked up anywhere on the page. From the anchors found, one uniform scale and a shift
are fitted (template grid -> document grid). An anchor counts as found when it sits where that
fit puts it, within the anchor tolerance. Linking scores on that count; reading places value
boxes through the same fit.

Uniform scale (one factor for both axes) is used on purpose: a photo zooms both axes together,
and the extra constraint stops two stray matches from always fitting.

The fit is made in page units, not grid units: a grid unit is 1/1000 of the page's width on x
and of its height on y, so on a photo of another shape (landscape vs portrait, owner retest
2026-10-21) the same card would need a different scale on each axis. A page unit is 1/1000 of
the page's longer side on both axes; the template side uses the page aspect stored in the
template, the document side the page's own.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from nabu.model.types import Box
from nabu.ocr.words import GRID, Page
from nabu.templates import centre_in, find_label, header, widen

MIN_SCALE, MAX_SCALE = 0.5, 2.0  # a phone photo's card size varies more than a scan's; provisional
MAX_MOVE = 200  # page units (20% of the longer side): framing, not another layout; provisional
MAX_PAIRS = 30  # anchors used for fitting on one page


def units(aspect: float | None) -> tuple[float, float]:
    """Page units per grid unit on (x, y) for a page of this width/height ratio."""
    if not aspect or aspect <= 0:
        return 1.0, 1.0
    return min(1.0, aspect), min(1.0, 1 / aspect)


def page_aspect(t: dict, page_n: int) -> float | None:
    """The template's stored aspect for page `page_n` (1-based), if any."""
    shapes = header(t).get("pages") or []
    return (shapes[page_n - 1] or {}).get("aspect") if 0 < page_n <= len(shapes) else None


@dataclass(frozen=True)
class Fit:
    """Template grid -> document grid: scale `s` and shift (tx, ty) in page units, with the
    page units per grid unit of the template (tu) and of the document (du)."""
    s: float = 1.0
    tx: float = 0.0
    ty: float = 0.0
    tu: tuple[float, float] = (1.0, 1.0)
    du: tuple[float, float] = (1.0, 1.0)

    def box(self, b: Box) -> Box:
        (ax, ay), (bx, by) = self.tu, self.du
        x0, y0 = (self.s * b[0] * ax + self.tx) / bx, (self.s * b[1] * ay + self.ty) / by
        x1, y1 = (self.s * b[2] * ax + self.tx) / bx, (self.s * b[3] * ay + self.ty) / by
        return (max(0, min(GRID, round(x0))), max(0, min(GRID, round(y0))),
                max(0, min(GRID, round(x1))), max(0, min(GRID, round(y1))))

    def offset(self, o: Box) -> Box:
        """A template offset (from a label box to its value box), on this document's grid."""
        kx, ky = self.s * self.tu[0] / self.du[0], self.s * self.tu[1] / self.du[1]
        return (round(o[0] * kx), round(o[1] * ky), round(o[2] * kx), round(o[3] * ky))


@dataclass
class Placement:
    fit: Fit = field(default_factory=Fit)
    total: int = 0  # anchors of the template on this page
    found: int = 0  # anchors found where the fit puts them
    hits: dict[int, tuple[Box, int, int]] = field(default_factory=dict)  # anchor index -> match


@dataclass(frozen=True)
class Anchor:
    text: str
    box: Box
    field: int | None  # index into the template's fields; None for a landmark


def anchors(t: dict, page_n: int) -> list[Anchor]:
    """The template's printed labels and landmarks on page `page_n` (1-based)."""
    out = []
    for i, f in enumerate(t.get("fields") or []):
        a = f.get("anchor") or {}
        if a.get("printed_label") and a.get("box") and a.get("page") == page_n:
            out.append(Anchor(a["printed_label"], tuple(a["box"]), i))  # type: ignore[arg-type]
    for lm in t.get("landmarks") or []:
        if lm.get("text") and lm.get("box") and lm.get("page") == page_n:
            out.append(Anchor(lm["text"], tuple(lm["box"]), None))  # type: ignore[arg-type]
    return out


def _centre(b: Box) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def fit(pairs: list[tuple[Box, Box]]) -> Fit:
    """Least-squares uniform scale + shift from template boxes to found boxes."""
    if not pairs:
        return Fit()
    src = [_centre(a) for a, _ in pairs]
    dst = [_centre(b) for _, b in pairs]
    if len(pairs) == 1:
        return Fit(1.0, dst[0][0] - src[0][0], dst[0][1] - src[0][1])
    mx, my = sum(p[0] for p in src) / len(src), sum(p[1] for p in src) / len(src)
    nx, ny = sum(p[0] for p in dst) / len(dst), sum(p[1] for p in dst) / len(dst)
    den = sum((x - mx) ** 2 + (y - my) ** 2 for x, y in src)
    if den < 50 ** 2:  # anchors too close together to tell zoom from shift
        s = 1.0
    else:
        num = sum((x - mx) * (u - nx) + (y - my) * (v - ny)
                  for (x, y), (u, v) in zip(src, dst, strict=True))
        s = min(MAX_SCALE, max(MIN_SCALE, num / den))
    return Fit(s, nx - s * mx, ny - s * my)


def _to_units(b: Box, u: tuple[float, float]) -> Box:
    return (b[0] * u[0], b[1] * u[1], b[2] * u[0], b[3] * u[1])  # type: ignore[return-value]


def place(items: list[Anchor], page: Page, tol: float, aspect: float | None = None) -> Placement:
    """Fit the template page onto `page` from its anchors. `aspect` is the template page's
    width/height (None: same shape as `page`). `hits` is keyed by position in `items`."""
    du = units((page.width_px or 0) / page.height_px if page.height_px else None)
    tu = units(aspect) if aspect else du
    if not items:
        return Placement(Fit(tu=tu, du=du))
    found: dict[int, tuple[Box, int, int]] = {}
    for i, a in enumerate(items):
        hit = find_label(a.text, page.words, near=a.box)
        if hit is not None:
            found[i] = hit
    # Fitted in page units; `on` gives the fit the grid conversions both ways.
    pairs = [(i, (_to_units(items[i].box, tu), _to_units(found[i][0], du)))
             for i in sorted(found)][:MAX_PAIRS]
    grid = {i: (items[i].box, found[i][0]) for i, _ in pairs}
    centroid = _mean([_centre(tb) for _, (tb, _) in pairs]) if pairs else (0.0, 0.0)

    def on(f: Fit) -> Fit:
        return replace(f, tu=tu, du=du)

    def agree(f: Fit) -> list[int]:
        g = on(f)
        return [i for i, (tb, fb) in grid.items() if centre_in(fb, widen(g.box(tb), tol))]

    def moved(f: Fit) -> float:
        cx, cy = centroid
        return max(abs(f.s * cx + f.tx - cx), abs(f.s * cy + f.ty - cy))

    # Candidates: no move, each single match (shift), each two matches (zoom + shift). The one
    # most anchors agree with wins (then the smaller move), refined on its anchors. A move over
    # MAX_MOVE is another layout, not another framing of this one.
    cands = [Fit()] + [fit([p]) for _, p in pairs]
    cands += [fit([p, q]) for k, (_, p) in enumerate(pairs) for _, q in pairs[k + 1:]]
    best, best_in = Fit(), agree(Fit())
    for c in cands:
        if moved(c) > MAX_MOVE:
            continue
        got = agree(c)
        if len(got) > len(best_in) or (len(got) == len(best_in) and moved(c) < moved(best)):
            best, best_in = c, got
    if len(best_in) >= 2:
        refined = fit([p for i, p in pairs if i in best_in])
        if moved(refined) <= MAX_MOVE and len(agree(refined)) >= len(best_in):
            best, best_in = refined, agree(refined)
    hits = {i: found[i] for i in best_in}
    return Placement(on(best), len(items), len(hits), hits)


def _mean(points: list[tuple[float, float]]) -> tuple[float, float]:
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)

