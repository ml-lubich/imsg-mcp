"""search_all correctness — the differentiator.

Messages stored as attributedBody blobs have text=NULL, so a plain
`text LIKE` search (search_messages) misses them. search_all decodes every
message and must find them. Runs on whichever engine is installed; the second
test pins the pure-Python path explicitly.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from imessage_mcp import HAVE_RUST, imessage


def test_search_all_finds_blob_messages_that_plain_search_misses(synthetic_db: Path):
    # synthetic_db: half the rows are blob-stored (text NULL). Both halves
    # contain the word "benchmark".
    plain = imessage.search_messages("benchmark", path=synthetic_db, limit=100)
    full = imessage.search_all("benchmark", path=synthetic_db, limit=100)
    assert len(full) > len(plain)  # full history recovers the blob-only rows
    assert all("benchmark" in (m.text or "") for m in full)


@pytest.mark.skipif(not HAVE_RUST, reason="Rust core not built")
def test_rust_and_python_search_all_agree(synthetic_db: Path, monkeypatch):
    rust_hits = {m.text for m in imessage.search_all("number", path=synthetic_db, limit=100)}
    monkeypatch.setattr(imessage, "_RUST", None)
    py_hits = {m.text for m in imessage.search_all("number", path=synthetic_db, limit=100)}
    assert rust_hits == py_hits and rust_hits


@pytest.mark.skipif(not HAVE_RUST, reason="Rust core not built")
def test_decode_many_matches_single(synthetic_db: Path):
    import imsgcore

    from bench.make_db import _attributed_body

    blobs = [_attributed_body(f"hello {i}") for i in range(200)]
    batched = imsgcore.decode_many(blobs)
    assert batched == [imsgcore.decode_attributed_body(b) for b in blobs]
    assert batched[0] == "hello 0"
