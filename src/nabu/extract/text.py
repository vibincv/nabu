"""TXT/MD/CSV/TSV/JSON from bytes; RTF and HTML best effort (FR-2.1, FR-3.1). M1.

Text files have no page positions: one page, words without boxes (AD-15). CSV and TSV rows keep
their cells so discovery can read key-value tables (FR-4.2).
"""

from __future__ import annotations

import csv
import html.parser
import io
import json
import re

from nabu.errors import UnreadableInput
from nabu.ocr.words import Line, Page, Reading, Word
from nabu.router import Kind

_MAX_JSON_DEPTH = 32


def decode(data: bytes, name: str) -> str:
    """UTF-8 (with or without BOM) or UTF-16 with BOM. Anything else is refused by name rather
    than shown as garbled text."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    else:
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            pass
    raise UnreadableInput(f"{name} is not UTF-8 or UTF-16 text; save it as UTF-8 and upload it again")


def text_line(s: str) -> Line:
    return Line(words=tuple(Word(text=t, box=None) for t in s.split()))


def row_line(cells: list[str]) -> Line:
    cells = [c.strip() for c in cells]
    return Line(words=tuple(Word(text=t, box=None) for c in cells for t in c.split()),
                cells=tuple(cells))


def _plain_lines(text: str) -> list[Line]:
    return [text_line(s) if "\t" not in s else row_line(s.split("\t"))
            for s in text.splitlines() if s.strip()]


def _rows(text: str, delimiter: str) -> list[Line]:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        return [row_line(r) for r in reader if any(c.strip() for c in r)]
    except csv.Error:
        raise UnreadableInput("the table file is damaged and could not be read") from None


def _json_lines(obj: object, path: str = "", depth: int = 0) -> list[Line]:
    """Flatten JSON to `key: value` lines; the key path is the label."""
    if depth > _MAX_JSON_DEPTH:
        raise UnreadableInput("the JSON file is nested too deeply to read")
    if isinstance(obj, dict):
        out: list[Line] = []
        for k, v in obj.items():
            out += _json_lines(v, f"{path} {k}".strip() if path else str(k), depth + 1)
        return out
    if isinstance(obj, list):
        out = []
        for i, v in enumerate(obj, 1):
            out += _json_lines(v, f"{path} {i}".strip(), depth + 1)
        return out
    value = "" if obj is None else str(obj).lower() if isinstance(obj, bool) else str(obj)
    return [row_line([path or "value", value])]


class _HtmlText(html.parser.HTMLParser):
    _BLOCK = frozenset({"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
                        "table", "section", "article", "header", "footer"})
    _SKIP = frozenset({"script", "style", "head", "title"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in self._SKIP:
            self._skip += 1
        elif tag in ("td", "th"):
            self.parts.append("\t")
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def _html_text(text: str) -> str:
    p = _HtmlText()
    p.feed(text)
    p.close()
    lines = [re.sub(r"[ \u00a0]+", " ", s).strip(" ").strip("\t") for s in "".join(p.parts).split("\n")]
    return "\n".join(s for s in lines if s.strip())


# \uN must come before the generic control word, which would otherwise swallow it.
_RTF_CONTROL = re.compile(
    r"\\u(?P<uni>-?\d+) ?|\\(?P<word>[a-z]+)(?P<arg>-?\d+)? ?|\\'(?P<hex>[0-9a-f]{2})"
    r"|\\(?P<escaped>[{}\\])|\\(?P<star>\*)|(?P<brace>[{}])", re.I)


def _rtf_text(text: str) -> str:
    """Plain text of simple RTF: paragraphs, tabs, \\'xx and \\u escapes. Destinations such as
    font tables and pictures are dropped. Best effort (FR-2.1)."""
    out: list[str] = []
    skip_depth: list[bool] = [False]
    pos = 0
    fallback = False  # \uN is followed by one fallback character for old readers; drop it
    for m in _RTF_CONTROL.finditer(text):
        between = text[pos:m.start()].replace("\r", "").replace("\n", "")
        if fallback and between:
            between, fallback = between[1:], False
        if not skip_depth[-1]:
            out.append(between)
        pos = m.end()
        word, hexchar, uni, escaped, star, brace = (
            m["word"], m["hex"], m["uni"], m["escaped"], m["star"], m["brace"])
        if hexchar and fallback:
            fallback = False
            continue
        fallback = False
        if brace == "{":
            skip_depth.append(skip_depth[-1])
        elif brace == "}":
            if len(skip_depth) > 1:
                skip_depth.pop()
        elif skip_depth[-1]:
            continue
        elif star:  # {\* ...} is an optional destination, never document text
            skip_depth[-1] = True
        elif escaped:
            out.append(escaped)
        elif hexchar:
            out.append(bytes([int(hexchar, 16)]).decode("cp1252", errors="replace"))
        elif uni:
            out.append(chr(int(uni) % 0x10000))
            fallback = True
        elif word in ("par", "line"):
            out.append("\n")
        elif word == "tab" or word == "cell":
            out.append("\t")
        elif word == "row":
            out.append("\n")
        elif word in ("fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "header",
                      "footer", "generator"):
            skip_depth[-1] = True
    if not skip_depth[-1]:
        out.append(text[pos:])
    return "".join(out)


def read(data: bytes, name: str, kind: Kind) -> Reading:
    text = decode(data, name)
    if kind == "csv":
        lines = _rows(text, ",")
    elif kind == "tsv":
        lines = _rows(text, "\t")
    elif kind == "json":
        try:
            lines = _json_lines(json.loads(text))
        except (ValueError, RecursionError):
            raise UnreadableInput(f"{name} is not valid JSON and could not be read") from None
    elif kind == "html":
        lines = _plain_lines(_html_text(text))
    elif kind == "rtf":
        lines = _plain_lines(_rtf_text(text))
    else:
        lines = _plain_lines(text)
    if not lines:
        raise UnreadableInput(f"{name} has no text to read")
    return Reading(file_name=name, route="text", pages=[Page(n=1, source="document", lines=lines)])
