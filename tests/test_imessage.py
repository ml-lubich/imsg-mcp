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


def test_dataclass_dict_helpers():
    chat = imessage.Chat(1, "id", "name", "iMessage")
    msg = imessage.Message("t", "+1", False, "2020", "iMessage", False)
    contact = imessage.Contact("+1", "iMessage")
    assert chat.dict()["identifier"] == "id"
    assert msg.dict()["text"] == "t"
    assert contact.dict()["handle"] == "+1"


def test_decode_attributed_body_empty_payload_after_marker():
    # NSString marker present but no length bytes follow
    blob = b"NSString" + b"\x00" * 5
    assert imessage._decode_attributed_body(blob) is None


def test_decode_attributed_body_two_byte_length_too_short():
    blob = b"NSString" + b"\x00" * 5 + bytes([0x81, 0x05])
    assert imessage._decode_attributed_body(blob) is None


def test_read_messages_filter_by_chat_id(synthetic_db: Path):
    chat_id = imessage.list_chats(path=synthetic_db, limit=1)[0].chat_id
    msgs = imessage.read_messages(chat_id=chat_id, path=synthetic_db, limit=10)
    assert msgs


# --- name resolution (AddressBook) -----------------------------------------


def test_find_contacts_by_name_exact(addressbook_db: Path):
    matches = imessage.find_contacts_by_name("Jordan Rivera", db_paths=[addressbook_db])
    assert matches == [("Jordan Rivera", ["+15550101234"])]


def test_find_contacts_by_name_case_insensitive(addressbook_db: Path):
    matches = imessage.find_contacts_by_name("rivera", db_paths=[addressbook_db])
    assert matches == [("Jordan Rivera", ["+15550101234"])]


def test_find_contacts_by_name_partial(addressbook_db: Path):
    matches = imessage.find_contacts_by_name("Riv", db_paths=[addressbook_db])
    assert [n for n, _ in matches] == ["Jordan Rivera"]


def test_find_contacts_by_name_ambiguous(addressbook_db: Path):
    matches = imessage.find_contacts_by_name("Jose", db_paths=[addressbook_db])
    assert {n for n, _ in matches} == {"Jose Alvarez", "Jose Ramirez"}


def test_find_contacts_by_name_none(addressbook_db: Path):
    assert imessage.find_contacts_by_name("Nobody Here", db_paths=[addressbook_db]) == []


def test_find_contacts_by_name_empty_query(addressbook_db: Path):
    assert imessage.find_contacts_by_name("  ", db_paths=[addressbook_db]) == []


def test_find_contacts_by_name_phone_normalisation(addressbook_db: Path):
    # "(555) 010-1234" -> +15550101234, matching chat.db's handle format.
    matches = imessage.find_contacts_by_name("Jordan", db_paths=[addressbook_db])
    assert matches == [("Jordan Rivera", ["+15550101234"])]


def test_find_contacts_by_name_email_handle(addressbook_db: Path):
    matches = imessage.find_contacts_by_name("Alvarez", db_paths=[addressbook_db])
    assert matches == [("Jose Alvarez", ["jose.alvarez@example.com"])]


def test_find_contacts_by_name_no_handle_contact_omitted(addressbook_db: Path):
    # "NoHandle Person" has no phone/email -> not a usable send target.
    assert imessage.find_contacts_by_name("NoHandle", db_paths=[addressbook_db]) == []


def test_find_contacts_by_name_missing_db_ignored(tmp_path: Path):
    assert imessage.find_contacts_by_name("anyone", db_paths=[tmp_path / "nope.abcddb"]) == []


def test_list_contacts_by_name_merges_and_dedupes(
    synthetic_db: Path, addressbook_db: Path
):
    rows = imessage.list_contacts(
        path=synthetic_db, addressbook_paths=[addressbook_db], query="Rivera"
    )
    assert rows == [imessage.Contact("+15550101234", None, "Jordan Rivera")]


def test_list_contacts_query_without_name_match_falls_back_to_handle_search(
    synthetic_db: Path, addressbook_db: Path
):
    handle = imessage.list_contacts(path=synthetic_db, limit=1)[0].handle
    needle = handle[:3]
    rows = imessage.list_contacts(
        path=synthetic_db, addressbook_paths=[addressbook_db], query=needle
    )
    assert rows and all(c.name is None for c in rows)


def test_pick_imessage_handle_single_handle_short_circuits():
    assert imessage._pick_imessage_handle(["+1"]) == "+1"


def test_pick_imessage_handle_prefers_known_imessage(synthetic_db: Path):
    known = imessage.list_contacts(path=synthetic_db, limit=1)[0].handle
    picked = imessage._pick_imessage_handle(
        [known, "unknown@example.com"], path=synthetic_db
    )
    assert picked == known


def test_resolve_recipient_passthrough_for_phone_and_email():
    assert imessage.resolve_recipient("+14155551234") == "+14155551234"
    assert imessage.resolve_recipient("a@example.com") == "a@example.com"


def test_resolve_recipient_by_name(addressbook_db: Path):
    resolved = imessage.resolve_recipient(
        "Jordan Rivera", addressbook_paths=[addressbook_db]
    )
    assert resolved == "+15550101234"


def test_resolve_recipient_ambiguous_raises(addressbook_db: Path):
    with pytest.raises(ValueError, match="ambiguous"):
        imessage.resolve_recipient("Jose", addressbook_paths=[addressbook_db])


def test_resolve_recipient_no_match_raises(addressbook_db: Path):
    with pytest.raises(ValueError, match="no contact"):
        imessage.resolve_recipient("Nobody", addressbook_paths=[addressbook_db])


def test_send_message_resolves_single_match(monkeypatch, addressbook_db: Path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    imessage.send_message("Jordan Rivera", "hi", addressbook_paths=[addressbook_db])
    assert "+15550101234" in captured["cmd"][2]


def test_send_message_refuses_ambiguous_name(monkeypatch, addressbook_db: Path):
    called = {"n": 0}

    def fake_run(cmd, **kwargs):
        called["n"] += 1
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ValueError, match="ambiguous"):
        imessage.send_message("Jose", "hi", addressbook_paths=[addressbook_db])
    assert called["n"] == 0


def test_send_message_refuses_no_match(monkeypatch, addressbook_db: Path):
    called = {"n": 0}
    monkeypatch.setattr(
        subprocess, "run",
        lambda cmd, **kw: called.__setitem__("n", called["n"] + 1),
    )
    with pytest.raises(ValueError, match="no contact"):
        imessage.send_message("Nobody", "hi", addressbook_paths=[addressbook_db])
    assert called["n"] == 0
