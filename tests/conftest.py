"""Shared fixtures: a small synthetic chat.db built with stdlib sqlite3.

Never reads a real Messages database.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bench.make_db import build  # noqa: E402


@pytest.fixture()
def synthetic_db(tmp_path: Path) -> Path:
    return build(tmp_path / "chat.db", n_messages=30, blob_fraction=0.5)
