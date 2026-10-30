"""Trial metrics (M6 task 0, owner 2026-10-30): on Verify, one log line of counts, so a
real-document trial is measured without counting edits by hand. Counts only: no field name,
printed label or value (FR-11.5).
"""

import logging
import re

from test_templates_api import (  # noqa: F401 (fixtures)
    A1,
    client,
    close,
    field,
    layout_a,
    open_doc,
    store,
)

LINE = re.compile(
    r"^verify metrics: pages=\d+ read_s=\d+\.\d link=(linked|similar|none) score=\d\.\d\d"
    r" fields=\d+ template=\d+ model=\d+ rules=\d+ added=\d+ edited=\d+ removed=\d+"
    r" needs_review=\d+->\d+ not_found=\d+->\d+$")
TYPED = "INV-9999"


def metrics(caplog):
    return [r.getMessage() for r in caplog.records
            if r.name.startswith("nabu") and r.getMessage().startswith("verify metrics")]


def test_verify_logs_counts_of_what_the_user_changed(client, caplog):  # noqa: F811
    doc_id, d = open_doc(client, layout_a(*A1))
    read = len(d["fields"])
    edit, drop = field(d, "Invoice"), field(d, "Total")
    caplog.set_level(logging.INFO)
    assert client.patch(f"/api/documents/{doc_id}/fields/{edit['id']}",
                        json={"value": TYPED}).status_code == 200
    assert client.patch(f"/api/documents/{doc_id}/fields/{drop['id']}",
                        json={"removed": True}).status_code == 200
    assert client.post(f"/api/documents/{doc_id}/fields", json={
        "name": "Extra", "page": 1, "box": [0, 0, 1000, 1000]}).status_code == 201
    assert client.post(f"/api/documents/{doc_id}/verify").status_code == 200

    [line] = metrics(caplog)
    assert LINE.match(line), line
    counts = dict(kv.split("=") for kv in line.removeprefix("verify metrics: ").split())
    assert counts["pages"] == "1" and counts["link"] == "none"
    assert counts["fields"] == str(read)  # kept: read - removed + added
    assert counts["rules"] == str(read - 1)  # the removed field is not counted as kept
    assert (counts["added"], counts["edited"], counts["removed"]) == ("1", "1", "1")
    assert counts["template"] == counts["model"] == "0"
    close(client, doc_id)


def test_metrics_line_carries_no_value_or_label(client, caplog):  # noqa: F811
    doc_id, d = open_doc(client, layout_a(*A1))
    caplog.set_level(logging.DEBUG)
    edit = field(d, "Invoice")
    client.patch(f"/api/documents/{doc_id}/fields/{edit['id']}", json={"value": TYPED})
    client.post(f"/api/documents/{doc_id}/verify")
    [line] = metrics(caplog)
    words = [*A1, TYPED, "Invoice", "Date", "Total", "invoice.pdf"]
    assert not any(w.casefold() in line.casefold() for w in words), line
    close(client, doc_id)


def test_each_verify_logs_one_line(client, caplog):  # noqa: F811
    doc_id, _ = open_doc(client, layout_a(*A1))
    caplog.set_level(logging.INFO)
    client.post(f"/api/documents/{doc_id}/verify")
    client.post(f"/api/documents/{doc_id}/verify")
    assert len(metrics(caplog)) == 2
    close(client, doc_id)
