"""Compare local models on a set of pages before switching (developer tool, M0).

    python -m nabu.model.evaluate CASES_DIR [--model qwen3.5:4b] [--runtime ollama]
                                            [--profile auto] [--endpoint URL]

CASES_DIR holds page images (`*.png`, `*.jpg`) and, for each, `<name>.expected.json`:

    {"ocr_text": "optional OCR text",
     "fields": [{"label": "Invoice No.", "value": "RE-2026-0412", "box": [660, 80, 902, 100]}]}

`box` is optional, on the 0-1000 grid. Output is one JSON report on stdout with metrics only:
case file names, counts, scores and timings. Document values are never printed, so a report
can be shared. This is not a document-reading command (FR-12.2): it produces no fields.

Metrics per case: whether the answer was valid JSON (after the one repair), label recall,
value accuracy on the labels found, seconds. `coords_fit` scores the model's raw boxes under
each convention (mean IoU with the expected boxes), which tells you which `coords` to set in the
model's profile.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from nabu import netguard
from nabu.config import Config, load_config
from nabu.errors import ModelOutputInvalid, NabuError
from nabu.model import images
from nabu.model.client import ModelClient
from nabu.model.types import Box, PageImage
from nabu.store.guard import compact, normalise
from nabu.store.paths import default_paths

CONVENTIONS = ("pixels", "grid_1000", "unit")


def _key(s: str | None) -> str:
    return compact(normalise(s or ""))


def iou(a: Box, b: Box) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def evaluate_case(client: ModelClient, image: Path, expected: dict) -> dict:
    data = image.read_bytes()
    w, h = images.image_size(data)
    page = images.fit(PageImage(data=data, width_px=w, height_px=h), client.max_edge)
    want = [f for f in expected.get("fields", []) if f.get("label")]
    result: dict = {"case": image.name, "expected_fields": len(want)}
    t0 = time.monotonic()
    try:
        found = client.discover_page(page, expected.get("ocr_text", "")).fields
    except ModelOutputInvalid:
        result.update(json_valid=False, seconds=round(time.monotonic() - t0, 2))
        return result
    result.update(json_valid=True, seconds=round(time.monotonic() - t0, 2),
                  returned_fields=len(found))
    by_label = {_key(f.label): f for f in found}
    matched = [(e, by_label[_key(e["label"])]) for e in want if _key(e["label"]) in by_label]
    result["label_recall"] = round(len(matched) / len(want), 3) if want else None
    values_ok = sum(1 for e, f in matched if _key(e.get("value")) == _key(f.value))
    result["value_accuracy"] = round(values_ok / len(matched), 3) if matched else None
    fits: dict[str, list[float]] = {c: [] for c in CONVENTIONS}
    for e, f in matched:
        if not e.get("box") or f.raw_box is None:
            continue
        exp = tuple(e["box"])
        for c in CONVENTIONS:
            got = images.to_grid(f.raw_box, c, page.width_px, page.height_px)  # type: ignore[arg-type]
            fits[c].append(iou(exp, got) if got else 0.0)  # type: ignore[arg-type]
    result["coords_fit"] = {c: round(sum(v) / len(v), 3) for c, v in fits.items() if v}
    return result


def _mean(rows: list[dict], key: str) -> float | None:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def evaluate(cfg: Config, cases_dir: Path) -> dict:
    cases = sorted(p for p in cases_dir.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    if not cases:
        raise NabuError(f"no page images in {cases_dir}")
    client = ModelClient(cfg)
    try:
        if not client.available():
            raise NabuError(f"the model {cfg.model} is not available. Run: nabu models pull {cfg.model}")
        rows = []
        for img in cases:
            exp_file = img.with_name(f"{img.stem}.expected.json")
            expected = json.loads(exp_file.read_text(encoding="utf-8")) if exp_file.exists() else {}
            rows.append(evaluate_case(client, img, expected))
    finally:
        client.close()
    fit_totals: dict[str, list[float]] = {}
    for r in rows:
        for c, v in r.get("coords_fit", {}).items():
            fit_totals.setdefault(c, []).append(v)
    coords_fit = {c: round(sum(v) / len(v), 3) for c, v in fit_totals.items()}
    best = max(coords_fit, key=coords_fit.__getitem__) if coords_fit else None
    return {
        "model": cfg.model, "runtime": cfg.model_runtime, "profile": client.profile.name,
        "cases": len(rows),
        "json_valid_rate": round(sum(1 for r in rows if r["json_valid"]) / len(rows), 3),
        "label_recall": _mean(rows, "label_recall"),
        "value_accuracy": _mean(rows, "value_accuracy"),
        "seconds_per_page": _mean(rows, "seconds"),
        "coords_fit": coords_fit,
        "suggested_coords": best if best and coords_fit[best] >= 0.5 else "none",
        "per_case": rows,
    }


def main(argv: list[str] | None = None) -> int:
    netguard.install()
    p = argparse.ArgumentParser(prog="python -m nabu.model.evaluate", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cases_dir", type=Path)
    p.add_argument("--model")
    p.add_argument("--runtime", choices=["ollama", "openai_compat"])
    p.add_argument("--profile")
    p.add_argument("--endpoint")
    args = p.parse_args(argv)
    try:
        cfg = load_config(default_paths().config_file, {
            "model": args.model, "model_runtime": args.runtime, "model_profile": args.profile,
            "model_endpoint": args.endpoint})
        if not cfg.model:
            raise NabuError("no model given. Use --model, or run: nabu models use <model>")
        print(json.dumps(evaluate(cfg, args.cases_dir), indent=2))  # noqa: T201
        return 0
    except NabuError as e:
        print(f"evaluate: {e.message}", file=sys.stderr)  # noqa: T201
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
