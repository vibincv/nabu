import json
import logging
import os
import stat
from importlib.resources import files

import jsonschema
import pytest

from nabu.hardening import configure_logging


def schema():
    return json.loads(files("nabu.schemas").joinpath("output.schema.json").read_text())


def test_sample_output_validates(fixtures_dir):
    sample = json.loads((fixtures_dir / "output.sample.json").read_text())
    jsonschema.validate(sample, schema())


def test_unknown_output_field_rejected(fixtures_dir):
    sample = json.loads((fixtures_dir / "output.sample.json").read_text())
    sample["fields"][0]["confidence"] = 0.9
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(sample, schema())


def test_logs_never_contain_exception_text_or_tracebacks(tmp_path):
    configure_logging(tmp_path / "logs")
    log = logging.getLogger("nabu.test")
    secret = "RE-2026-0412 Beispiel Bürobedarf GmbH"
    try:
        raise ValueError(f"could not parse line: {secret}")
    except ValueError:
        log.exception("reading failed for file %s", "synthetic.pdf")
    for h in logging.getLogger("nabu").handlers:
        h.flush()
    text = (tmp_path / "logs" / "nabu.log").read_text(encoding="utf-8")
    assert "synthetic.pdf" in text
    assert "ValueError" in text
    assert "RE-2026-0412" not in text and "Traceback" not in text


def test_working_result_fixture_is_synthetic(fixtures_dir):
    wr = json.loads((fixtures_dir / "working_result.sample.json").read_text())
    assert wr["document"]["source_file"].startswith("synthetic_")


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_log_file_is_user_only(tmp_path):
    configure_logging(tmp_path / "logs")
    assert stat.S_IMODE((tmp_path / "logs" / "nabu.log").stat().st_mode) == 0o600
