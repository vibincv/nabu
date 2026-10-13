"""Test setup. The egress guard is installed for the whole test run, so every test runs with
the same "only this machine" rule the product enforces (NFR-1, FR-11.2)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from nabu import netguard  # noqa: E402

netguard.install()

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def nabu_home(tmp_path, monkeypatch):
    home = tmp_path / "nabu-home"
    monkeypatch.setenv("NABU_HOME", str(home))
    return home


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
