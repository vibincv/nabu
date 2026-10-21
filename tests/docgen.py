"""Synthetic test documents, built in memory at test time (fixtures are synthetic only).

PDFs are written by hand (text in Helvetica/WinAnsi, optional AcroForm fields, optional image
pages), so no PDF-writing dependency is needed. Images use Pillow's built-in scalable font
(Latin only). Office files use the reading stack's own libraries.
"""

from __future__ import annotations

import io
import zlib


def _esc(s: str) -> bytes:
    b = s.encode("cp1252")
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


class _Pdf:
    def __init__(self) -> None:
        self.objs: list[bytes] = []

    def add(self, body: bytes) -> int:
        self.objs.append(body)
        return len(self.objs)

    def set(self, n: int, body: bytes) -> None:
        self.objs[n - 1] = body

    def bytes(self, root: int, trailer_extra: bytes = b"") -> bytes:
        out = io.BytesIO()
        out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(self.objs, 1):
            offsets.append(out.tell())
            out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
        xref = out.tell()
        out.write(f"xref\n0 {len(self.objs) + 1}\n0000000000 65535 f \n".encode())
        for o in offsets:
            out.write(f"{o:010d} 00000 n \n".encode())
        out.write(f"trailer\n<< /Size {len(self.objs) + 1} /Root {root} 0 R ".encode()
                  + trailer_extra + f">>\nstartxref\n{xref}\n%%EOF\n".encode())
        return out.getvalue()


def pdf(pages: list[list[tuple[float, float, str]] | bytes], *, size: int = 11,
        form: list[tuple[str, str, int, tuple[float, float, float, float]]] = (),
        encrypted: bool = False, page: tuple[int, int] = (595, 842)) -> bytes:
    """PDF, A4 unless `page` (width, height in points) says otherwise. Each page is a list of
    (x_pt, y_pt_from_top, text) or JPEG bytes (a scanned page).
    `form` adds AcroForm text fields: (name, value, page index, rect in points from bottom)."""
    w, h = page
    doc = _Pdf()
    catalog = doc.add(b"")
    pages_obj = doc.add(b"")
    font = doc.add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    kids = []
    for content in pages:
        if isinstance(content, bytes):  # JPEG scan filling the page
            from PIL import Image

            iw, ih = Image.open(io.BytesIO(content)).size
            img = doc.add(f"<< /Type /XObject /Subtype /Image /Width {iw} /Height {ih} "
                          f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
                          f"/Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
            stream = f"q {w} 0 0 {h} 0 0 cm /Im1 Do Q".encode()
            res = f"<< /XObject << /Im1 {img} 0 R >> >>".encode()
        else:
            ops = [b"BT", f"/F1 {size} Tf".encode()]
            for x, y, text in content:
                ops.append(f"1 0 0 1 {x} {h - y} Tm".encode() + b" (" + _esc(text) + b") Tj")
            ops.append(b"ET")
            stream = zlib.compress(b"\n".join(ops))
            res = f"<< /Font << /F1 {font} 0 R >> >>".encode()
            stream = f"<< /Length {len(stream)} /Filter /FlateDecode >>\nstream\n".encode() \
                + stream + b"\nendstream"
            content_obj = doc.add(stream)
            kids.append(doc.add(f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 {w} {h}] "
                                f"/Resources ".encode() + res
                                + f" /Contents {content_obj} 0 R >>".encode()))
            continue
        content_obj = doc.add(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream
                              + b"\nendstream")
        kids.append(doc.add(f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 {w} {h}] "
                            f"/Resources ".encode() + res + f" /Contents {content_obj} 0 R >>".encode()))
    fields = []
    for name, value, page_i, rect in form:
        fields.append(doc.add(
            b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (" + _esc(name)
            + b") /V (" + _esc(value) + b") /Rect [" + " ".join(str(v) for v in rect).encode()
            + f"] /P {kids[page_i]} 0 R >>".encode()))
    doc.set(pages_obj, f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] "
                       f"/Count {len(kids)} >>".encode())
    acro = (f" /AcroForm << /Fields [{' '.join(f'{f} 0 R' for f in fields)}] >>" if fields
            else "").encode()
    doc.set(catalog, f"<< /Type /Catalog /Pages {pages_obj} 0 R".encode() + acro + b" >>")
    extra = b""
    if encrypted:  # a standard-handler dictionary whose user password is not empty
        enc = doc.add(b"<< /Filter /Standard /V 1 /R 2 /Length 40 /P -44 "
                      b"/O <" + b"11" * 32 + b"> /U <" + b"22" * 32 + b"> >>")
        extra = f"/Encrypt {enc} 0 R /ID [<{'ab' * 16}> <{'ab' * 16}>] ".encode()
    return doc.bytes(catalog, extra)


def page_image(rows: list[tuple[str, str]], *, title: str | None = None, fmt: str = "PNG",
               size: tuple[int, int] = (1240, 1754), font_px: int = 34) -> bytes:
    """A clean synthetic scan: "Label: value" rows in two columns, Latin text."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=font_px)
    y = 90
    if title:
        d.text((80, y), title, font=ImageFont.load_default(size=font_px + 16), fill="black")
        y += 110
    for label, value in rows:
        d.text((80, y), label, font=font, fill="black")
        d.text((560, y), value, font=font, fill="black")
        y += 80
    buf = io.BytesIO()
    img.save(buf, format=fmt, **({"quality": 92} if fmt == "JPEG" else {}))
    return buf.getvalue()


def docx(paragraphs: list[str], table: list[list[str]] = ()) -> bytes:
    import docx as _docx

    d = _docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    if table:
        t = d.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, cell in enumerate(row):
                t.cell(r, c).text = cell
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def xlsx(sheets: dict[str, list[list[object]]]) -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def pptx(slides: list[list[str]]) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    for lines in slides:
        s = prs.slides.add_slide(prs.slide_layouts[5])
        box = s.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(4))
        box.text_frame.text = lines[0]
        for line in lines[1:]:
            box.text_frame.add_paragraph().text = line
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
