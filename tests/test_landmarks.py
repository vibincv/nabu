"""Templates for documents without printed labels (M3 fix, 2026-10-14): an ID card prints its
values with no "Name:" beside them. Found by the owner on a PAN card, where the template stored
no anchors, linked at 0.00 and read nothing.

Fixed printed text (landmarks) lets such a template link, and one scale + shift fitted from the
anchors places the values on a card that is framed differently (templates.align).
"""

import json

import docgen
import pytest
from test_templates_api import client, close, open_doc, store, wait_ready  # noqa: F401 (fixtures)

from nabu.config import Config
from nabu.ocr.words import Line, Page, Word
from nabu.templates import align

pytest.importorskip("pypdfium2")

STATIC = ["INCOME TAX DEPARTMENT", "GOVT OF INDIA", "Permanent Account Number Card", "Signature"]
NAMES = ["Full Name", "Father Name", "Date of Birth", "PAN"]
CARD1 = ("RAVI KUMAR SHARMA", "MOHAN LAL SHARMA", "14/08/1987", "ABCPS1234K")
CARD2 = ("ANITA DESAI", "PRAKASH DESAI", "02/11/1990", "BQRPD5678M")
Y = [200, 240, 280, 320]  # value baselines, points from the top


def card(values, dx=0.0, dy=0.0, s=1.0, page=(595, 842)):
    def at(x, y):
        return dx + s * x, dy + s * y
    lines = [(*at(60, 60), STATIC[0]), (*at(330, 60), STATIC[1]), (*at(60, 100), STATIC[2]),
             (*at(60, 420), STATIC[3])]
    lines += [(*at(60, y), v) for y, v in zip(Y, values, strict=True)]
    return docgen.pdf([lines], page=page)


def grid_box(y_pt):  # a box around a value line on the 0-1000 grid of an A4 page
    return [90, round((y_pt - 13) / 842 * 1000), 700, round((y_pt + 4) / 842 * 1000)]


def learn_card(c, excluded=("Signature",)):
    doc_id, d = open_doc(c, card(CARD1), "pan1.pdf")
    assert d["link"]["outcome"] == "none"
    base = f"/api/documents/{doc_id}"
    # The rules read the header as a pair ("INCOME TAX DEPARTMENT" -> "GOVT OF INDIA"), as on a
    # real PAN card; the user removes it.
    assert [f["printed_label"] for f in d["fields"]] == [STATIC[0]]
    c.patch(f"{base}/fields/{d['fields'][0]['id']}", json={"removed": True})
    for name, y in zip(NAMES, Y, strict=True):  # no printed labels: the user draws each field
        r = c.post(f"{base}/fields", json={"name": name, "page": 1, "box": grid_box(y)})
        assert r.status_code == 201, r.text
    s = c.post(f"{base}/verify").json()
    assert s["labels"] == []  # nothing printed beside the values
    # Fixed text only. "GOVT OF INDIA" was the removed field's value, so it is never kept.
    assert s["landmarks"]["new"] == [STATIC[0], STATIC[2], STATIC[3]]
    r = c.post(f"{base}/save", json={"choice": "new", "document_type": "ID card", "region": "IN",
                                     "format": "PAN card", "landmarks_excluded": list(excluded)})
    assert r.status_code == 200, r.text
    tid = json.loads(c.get(f"{base}/output").content)["template_id"]
    close(c, doc_id)
    return tid


def values_of(d):
    return {f["name"]: f["value"] for f in d["fields"]}


def test_label_less_card_links_and_reads(client, store, nabu_home):  # noqa: F811
    tid = learn_card(client)
    t = store.load_template(tid)
    assert [lm["text"] for lm in t["landmarks"]] == [STATIC[0], STATIC[2]]  # "Signature" left out
    blob = "".join(p.read_text(encoding="utf-8") for p in nabu_home.rglob("*.json"))
    assert not any(v in blob for v in CARD1)  # AR-7: no value on disk

    doc_id, d = open_doc(client, card(CARD2), "pan2.pdf")
    assert d["link"]["outcome"] == "linked" and d["link"]["template_id"] == tid
    assert values_of(d) == dict(zip(NAMES, CARD2, strict=True))
    assert not any("needs_review" in f["status"] for f in d["fields"])
    close(client, doc_id)


def test_card_framed_differently_still_reads(client, store):  # noqa: F811  (phone photo)
    # Zoom is measured from landmarks spread over the card: the bottom "Signature" line is kept.
    # With only the two top lines, zoom cannot be told from a shift (a documented limit).
    learn_card(client, excluded=())
    doc_id, d = open_doc(client, card(CARD2, dx=25, dy=-30, s=0.92), "pan3.pdf")
    assert d["link"]["outcome"] == "linked"
    assert values_of(d) == dict(zip(NAMES, CARD2, strict=True))
    close(client, doc_id)


def test_other_document_does_not_link(client, store):  # noqa: F811
    learn_card(client)
    other = docgen.pdf([[(60, 80, "Invoice no: INV-1"), (60, 110, "Total: 5.00 EUR")]])
    doc_id, d = open_doc(client, other, "invoice.pdf")
    assert d["link"]["outcome"] == "none"
    close(client, doc_id)


# Owner retest 2026-10-21: a second PAN photo of another shape scored 0 on the page-shape check
# before any landmark was looked at. A photo's shape is the camera's framing, not the card's.
@pytest.mark.parametrize(("page", "s"), [((842, 595), 0.9), ((595, 1058), 0.9),
                                         ((842, 595), 0.6)],
                         ids=["landscape", "tall_phone", "landscape_far"])
def test_card_on_a_photo_of_another_shape_links_and_reads(client, store, page, s):  # noqa: F811
    tid = learn_card(client, excluded=())
    doc_id, d = open_doc(client, card(CARD2, dx=40, dy=30, s=s, page=page), "pan5.pdf")
    assert d["link"]["outcome"] == "linked" and d["link"]["template_id"] == tid
    assert values_of(d) == dict(zip(NAMES, CARD2, strict=True))
    close(client, doc_id)


def test_other_document_on_another_shape_does_not_link(client, store):  # noqa: F811
    learn_card(client, excluded=())
    other = docgen.pdf([[(60, 80, "Invoice no: INV-1"), (60, 110, "Total: 5.00 EUR")]],
                       page=(842, 595))
    doc_id, d = open_doc(client, other, "invoice.pdf")
    assert d["link"]["outcome"] == "none"
    close(client, doc_id)


def test_update_from_a_photo_of_another_shape_still_links(client, store):  # noqa: F811
    # The update records the new photo's shape, so the kept landmarks must be where they are on
    # the new photo, not where they were on the old one.
    tid = learn_card(client, excluded=())
    landscape = (842, 595)
    doc_id, d = open_doc(client, card(CARD2, dx=40, dy=30, s=0.9, page=landscape), "pan6.pdf")
    base = f"/api/documents/{doc_id}"
    client.post(f"{base}/verify")
    assert client.post(f"{base}/save", json={"choice": "update", "template_id": tid}).status_code == 200
    close(client, doc_id)
    doc_id, d = open_doc(client, card(CARD1, page=landscape), "pan7.pdf")
    assert d["link"]["outcome"] == "linked" and d["link"]["template_id"] == tid
    assert values_of(d) == dict(zip(NAMES, CARD1, strict=True))
    close(client, doc_id)


def test_update_keeps_only_landmarks_seen_again(client, store):  # noqa: F811
    tid = learn_card(client)
    # A card without the "GOVT OF INDIA" line: an update must drop it, never add new text.
    lines = [(60, 60, STATIC[0]), (60, 100, STATIC[2]), (60, 140, "NEW PRINTED LINE HERE")]
    lines += [(60, y, v) for y, v in zip(Y, CARD2, strict=True)]
    doc_id, d = open_doc(client, docgen.pdf([lines]), "pan4.pdf")
    base = f"/api/documents/{doc_id}"
    if d["link"]["outcome"] != "linked":
        client.put(f"{base}/link", json={"template_id": tid})
        d = wait_ready(client, doc_id)
    client.patch(f"{base}/fields/{d['fields'][0]['id']}", json={"name": "Holder"})
    s = client.post(f"{base}/verify").json()
    assert s["landmarks"]["update"] == [STATIC[0], STATIC[2]]
    assert client.post(f"{base}/save", json={"choice": "update", "template_id": tid}).status_code == 200
    assert [lm["text"] for lm in store.load_template(tid)["landmarks"]] == [STATIC[0], STATIC[2]]
    close(client, doc_id)


# Owner retest 2026-10-28: DOB read the date, the name and printed card text. Each update stored
# the box of what was read, so the box grew by a line per save. Here the printed line sits just
# under the date, as "Permanent Account Number" does on a real PAN card.
TIGHT = "Permanent Account Number"


def tight_card(values, dx=0.0, dy=0.0):
    lines = [(dx + 60, dy + 60, STATIC[0]), (dx + 60, dy + 100, STATIC[2]),
             (dx + 60, dy + 294, TIGHT), (dx + 60, dy + 420, STATIC[3])]
    lines += [(dx + 60, dy + y, v) for y, v in zip(Y, values, strict=True)]
    return docgen.pdf([lines])


def learn_tight(c, boxes=None):
    doc_id, d = open_doc(c, tight_card(CARD1), "pan1.pdf")
    base = f"/api/documents/{doc_id}"
    for f in d["fields"]:
        c.patch(f"{base}/fields/{f['id']}", json={"removed": True})
    for name, y in zip(NAMES, Y, strict=True):
        box = (boxes or {}).get(name) or grid_box(y)
        assert c.post(f"{base}/fields", json={"name": name, "page": 1, "box": box}).status_code == 201
    c.post(f"{base}/verify")
    r = c.post(f"{base}/save", json={"choice": "new", "document_type": "ID card", "region": "IN",
                                     "format": "PAN card"})
    assert r.status_code == 200, r.text
    tid = json.loads(c.get(f"{base}/output").content)["template_id"]
    close(c, doc_id)
    return tid


def dob_height(st, tid):
    o = next(f for f in st.load_template(tid)["fields"] if f["name"] == "Date of Birth")
    return o["anchor"]["value_offset"][3] - o["anchor"]["value_offset"][1]


def test_printed_line_under_a_value_is_not_read(client, store):  # noqa: F811
    tid = learn_tight(client)
    assert TIGHT in [lm["text"] for lm in store.load_template(tid)["landmarks"]]
    doc_id, d = open_doc(client, tight_card(CARD2, dx=10, dy=6), "pan2.pdf")
    assert d["link"]["outcome"] == "linked"
    assert values_of(d) == dict(zip(NAMES, CARD2, strict=True))
    close(client, doc_id)


def test_landmark_inside_a_grown_box_is_not_read(client, store, nabu_home):  # noqa: F811
    tid = learn_tight(client)
    path = next(p for p in nabu_home.rglob("*.json")
                if "versions" not in p.parts and json.loads(p.read_text("utf-8")).get("template",
                                                                                    {}).get("id") == tid)
    t = json.loads(path.read_text("utf-8"))  # a box grown before this fix (the owner's v3)
    dob = next(f for f in t["fields"] if f["name"] == "Date of Birth")
    dob["anchor"]["value_offset"][3] = grid_box(294)[3]
    path.write_text(json.dumps(t), "utf-8")
    doc_id, d = open_doc(client, tight_card(CARD2), "pan2.pdf")
    assert values_of(d)["Date of Birth"] == CARD2[2]
    close(client, doc_id)


def test_edited_value_moves_the_box_so_updates_do_not_grow_it(client, store):  # noqa: F811
    tall = [grid_box(Y[2])[0], grid_box(Y[2])[1], grid_box(Y[2])[2], grid_box(Y[3])[3]]
    tid = learn_tight(client, boxes={"Date of Birth": tall})  # drawn over two lines by mistake
    doc_id, d = open_doc(client, tight_card(CARD2), "pan2.pdf")
    base = f"/api/documents/{doc_id}"
    dob = next(f for f in d["fields"] if f["name"] == "Date of Birth")
    assert dob["value"] != CARD2[2]  # two lines read: the box says so
    client.patch(f"{base}/fields/{dob['id']}", json={"value": CARD2[2]})
    client.post(f"{base}/verify")
    assert client.post(f"{base}/save", json={"choice": "update", "template_id": tid}).status_code == 200
    close(client, doc_id)
    assert dob_height(store, tid) < 30  # one line, where the date is printed
    doc_id, d = open_doc(client, tight_card(CARD1, dx=8, dy=5), "pan3.pdf")
    assert values_of(d)["Date of Birth"] == CARD1[2]
    close(client, doc_id)


# ---- the fit itself --------------------------------------------------------------------------

def page_of(items, width=595, height=842):
    words = [Word(text, box) for text, box in items]
    return Page(n=1, source="text_layer", lines=[Line((w,)) for w in words], width_px=width,
                height_px=height)


def test_fit_finds_zoom_and_shift():
    anchors = [align.Anchor("AAAAAA", (100, 100, 200, 120), None),
               align.Anchor("BBBBBB", (600, 100, 700, 120), None),
               align.Anchor("CCCCCC", (100, 700, 200, 720), None)]
    moved = [(a.text, align.Fit(0.9, 40, -20).box(a.box)) for a in anchors]
    pl = align.place(anchors, page_of(moved), Config().anchor_tolerance)
    assert pl.found == 3 and abs(pl.fit.s - 0.9) < 0.01


def test_fit_across_page_shapes():
    # Template on a portrait page (aspect 0.7); the same layout photographed landscape (1.4):
    # each grid unit is a different length on x and y, but the card itself is not stretched.
    anchors = [align.Anchor("AAAAAA", (100, 100, 200, 120), None),
               align.Anchor("BBBBBB", (600, 100, 700, 120), None),
               align.Anchor("CCCCCC", (100, 700, 200, 720), None)]
    want = align.Fit(0.9, 40, 20, tu=align.units(0.7), du=align.units(1.4))
    moved = [(a.text, want.box(a.box)) for a in anchors]
    pl = align.place(anchors, page_of(moved, 842, 601), Config().anchor_tolerance, aspect=0.7)
    assert pl.found == 3 and abs(pl.fit.s - 0.9) < 0.01


def test_fit_refuses_a_different_layout():
    anchors = [align.Anchor("AAAAAA", (100, 100, 200, 120), None),
               align.Anchor("BBBBBB", (100, 200, 200, 220), None)]
    far = [(a.text, align.Fit(1.0, 300, 400).box(a.box)) for a in anchors]  # moved 30-40%
    assert align.place(anchors, page_of(far), Config().anchor_tolerance).found == 0
