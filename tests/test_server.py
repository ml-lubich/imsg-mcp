"""MCP server tool tests (stdio entry mocked)."""
from __future__ import annotations

import pytest

from imessage_mcp import imessage, server


def test_check_access_ok(monkeypatch):
    monkeypatch.setattr(
        imessage, "list_chats", lambda limit=1: [imessage.Chat(1, "c", "C", "iMessage")]
    )
    assert "ok:" in server.check_access()
    assert "readable" in server.check_access()


def test_check_access_error(monkeypatch):
    def boom(limit=1):
        raise imessage.AccessError("denied")

    monkeypatch.setattr(imessage, "list_chats", boom)
    assert server.check_access().startswith("error:")


def test_list_chats_tool(monkeypatch):
    monkeypatch.setattr(
        imessage, "list_chats",
        lambda limit=20: [imessage.Chat(2, "chat2", "Two", "SMS")],
    )
    rows = server.list_chats(limit=5)
    assert rows == [{"chat_id": 2, "identifier": "chat2", "name": "Two", "service": "SMS"}]


def test_list_contacts_tool(monkeypatch):
    monkeypatch.setattr(
        imessage, "list_contacts",
        lambda limit=100, query=None: [imessage.Contact("+1", "iMessage")],
    )
    rows = server.list_contacts(limit=10, query="1")
    assert rows == [{"handle": "+1", "service": "iMessage"}]


def test_get_recent_messages_tool(monkeypatch):
    monkeypatch.setattr(
        imessage, "read_messages",
        lambda contact=None, chat_id=None, limit=20: [
            imessage.Message("hi", "+1", False, "2020-01-01", "iMessage", False)
        ],
    )
    rows = server.get_recent_messages(contact="+1", limit=1)
    assert rows[0]["text"] == "hi"


def test_search_messages_tool(monkeypatch):
    monkeypatch.setattr(
        imessage, "search_all",
        lambda query, limit=20: [
            imessage.Message("dinner", "me", True, "2020-01-01", "iMessage", False)
        ],
    )
    rows = server.search_messages("dinner", limit=5)
    assert rows[0]["is_from_me"] is True


def test_send_message_tool(monkeypatch):
    seen: dict[str, str] = {}
    monkeypatch.setattr(
        imessage, "send_message", lambda r, t: seen.update(recipient=r, text=t)
    )
    assert server.send_message("+1", "ping") == "sent to +1"
    assert seen == {"recipient": "+1", "text": "ping"}


def test_main_invokes_mcp_run(monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(server.mcp, "run", lambda: called.__setitem__("n", called["n"] + 1))
    server.main()
    assert called["n"] == 1


def test_list_attachments_tool(monkeypatch):
    monkeypatch.setattr(
        imessage, "list_attachments",
        lambda contact=None, chat_id=None, limit=20, kind=None: [
            imessage.Attachment(
                message_id=7, chat_id=2, filename="/tmp/x/clip.caf",
                mime_type="audio/x-caf", transfer_name="clip.caf", total_bytes=99,
                date="2026-08-04T10:00:00", is_from_me=False, sender="+1",
                exists=True,
            )
        ],
    )
    rows = server.list_attachments(kind="audio", limit=5)
    assert rows[0]["transfer_name"] == "clip.caf"
    assert rows[0]["mime_type"] == "audio/x-caf"
    assert rows[0]["exists"] is True


def test_download_attachments_tool(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(
        imessage, "download_attachments",
        lambda d, contact=None, chat_id=None, limit=20, kind=None: [Path(d) / "clip.caf"],
    )
    out = server.download_attachments("/tmp/dest", kind="audio")
    assert out == ["/tmp/dest/clip.caf"]
    assert all(isinstance(p, str) for p in out)
