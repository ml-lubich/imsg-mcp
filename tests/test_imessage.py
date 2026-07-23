"""Tests for the core read/decode/send logic (pure-Python path).

If the Rust core is installed it is exercised too, since the public functions
delegate to it; forcing _RUST=None here pins the pure-Python behavior.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bench.make_db import _attributed_body
from imessage_mcp import imessage


@pytest.fixture(autouse=True)
def _force_python(monkeypatch):
    monkeypatch.setattr(imessage, "_RUST", None)


def test_decode_attributed_body_roundtrip():
    assert imessage._decode_attributed_body(_attributed_body("hello world")) == "hello world"


def test_decode_attributed_body_long_string():
    text = "x" * 500  # forces the 0x81 two-byte length branch
    assert imessage._decode_attributed_body(_attributed_body(text)) == text


def test_decode_attributed_body_none():
    assert imessage._decode_attributed_body(None) is None
    assert imessage._decode_attributed_body(b"no marker here") is None


def test_apple_time_conversion_handles_ns_and_seconds():
    # 0 -> None; ns and seconds both land on the same wall clock.
    assert imessage._apple_time_to_iso(0) is None
    ns = imessage._apple_time_to_iso(700_000_000 * 1_000_000_000)
    sec = imessage._apple_time_to_iso(700_000_000)
    assert ns == sec and ns.startswith("2023")


def test_read_messages_decodes_blob_rows(synthetic_db: Path):
    msgs = imessage.read_messages(path=synthetic_db, limit=30)
    assert len(msgs) == 30
    assert all(m.text for m in msgs)  # every row resolved, incl. blob-only ones
    assert msgs[0].date < msgs[-1].date  # chronological (oldest first)


def test_read_messages_filter_by_contact(synthetic_db: Path):
    contact = imessage.list_contacts(path=synthetic_db, limit=1)[0].handle
    msgs = imessage.read_messages(contact=contact, path=synthetic_db, limit=50)
    assert msgs and all(m.is_from_me or m.sender == contact for m in msgs)


def test_search_messages(synthetic_db: Path):
    hits = imessage.search_messages("benchmark", path=synthetic_db, limit=50)
    assert hits and all("benchmark" in (m.text or "") for m in hits)


def test_list_chats(synthetic_db: Path):
    chats = imessage.list_chats(path=synthetic_db, limit=20)
    assert chats and chats[0].identifier.startswith("chat")


def test_list_contacts_and_query(synthetic_db: Path):
    all_contacts = imessage.list_contacts(path=synthetic_db, limit=100)
    assert all_contacts
    handle = all_contacts[0].handle
    needle = handle[:3]
    filtered = imessage.list_contacts(path=synthetic_db, limit=100, query=needle)
    assert filtered and all(needle.lower() in c.handle.lower() for c in filtered)


def test_missing_db_raises_access_error(tmp_path: Path):
    with pytest.raises(imessage.AccessError):
        imessage.list_chats(path=tmp_path / "nope.db")


def test_send_message_escapes_and_invokes_osascript(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    imessage.send_message("+14155551234", 'hi "there" \\o/')
    script = captured["cmd"][2]
    assert '\\"there\\"' in script and "+14155551234" in script


def test_rust_runtime_error_becomes_access_error(monkeypatch):
    class FakeRust:
        def list_chats(self, *a):
            raise RuntimeError("unable to open database file")

    monkeypatch.setattr(imessage, "_RUST", FakeRust())
    with pytest.raises(imessage.AccessError, match="Full Disk Access"):
        imessage.list_chats()


def test_send_message_requires_fields():
    with pytest.raises(ValueError):
        imessage.send_message("", "x")


def test_send_message_raises_on_osascript_failure(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "boom"),
    )
    with pytest.raises(RuntimeError, match="boom"):
        imessage.send_message("+1", "hi")
