"""CLI smoke tests via typer's CliRunner, with core functions monkeypatched."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from imessage_mcp import imessage, main

runner = CliRunner()

_COMMANDS = ("doctor", "chats", "contacts", "read", "search", "send", "version", "help")


def test_version():
    result = runner.invoke(main.app, ["version"])
    assert result.exit_code == 0 and "imsg" in result.stdout


def test_root_short_help():
    result = runner.invoke(main.app, ["-h"])
    assert result.exit_code == 0
    assert "contacts" in result.stdout
    assert "Agent-friendly" in result.stdout or "imsg contacts" in result.stdout


def test_agent_help_sheet():
    result = runner.invoke(main.app, ["help"])
    assert result.exit_code == 0
    assert "imsg contacts" in result.stdout
    assert "list_contacts" in result.stdout
    assert "\n  contacts" in result.stdout or "contacts [-n" in result.stdout


def test_help_command_delegates():
    result = runner.invoke(main.app, ["help", "contacts"])
    assert result.exit_code == 0
    assert "Usage:" in result.stdout
    assert "--query" in result.stdout or "-q" in result.stdout


@pytest.mark.parametrize("cmd", _COMMANDS)
@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_command_help_flags(cmd: str, flag: str):
    result = runner.invoke(main.app, [cmd, flag])
    assert result.exit_code == 0, result.stdout
    assert "Usage:" in result.stdout


def test_chats_renders(monkeypatch):
    monkeypatch.setattr(
        imessage, "list_chats",
        lambda limit=20: [imessage.Chat(1, "chat1", "Chat One", "iMessage")],
    )
    result = runner.invoke(main.app, ["chats"])
    assert result.exit_code == 0 and "chat1" in result.stdout


def test_contacts_renders(monkeypatch):
    monkeypatch.setattr(
        imessage, "list_contacts",
        lambda limit=100, query=None: [
            imessage.Contact("+14155551234", "iMessage"),
            imessage.Contact("a@example.com", "iMessage"),
        ],
    )
    result = runner.invoke(main.app, ["contacts", "-n", "10"])
    assert result.exit_code == 0
    assert "+14155551234" in result.stdout
    assert "a@example.com" in result.stdout
    assert "handle" in result.stdout.lower() or "Contacts" in result.stdout


def test_contacts_query_forwarded(monkeypatch):
    seen: dict[str, object] = {}

    def fake_list_contacts(limit=100, query=None):
        seen["limit"] = limit
        seen["query"] = query
        return [imessage.Contact("+14155551234", "iMessage")]

    monkeypatch.setattr(imessage, "list_contacts", fake_list_contacts)
    result = runner.invoke(main.app, ["contacts", "-q", "415", "--limit", "5"])
    assert result.exit_code == 0
    assert seen == {"limit": 5, "query": "415"}
    assert "+14155551234" in result.stdout


def test_send_reports_sent(monkeypatch):
    sent = {}
    monkeypatch.setattr(imessage, "send_message", lambda r, t: sent.update(r=r, t=t))
    result = runner.invoke(main.app, ["send", "+14155551234", "hello"])
    assert result.exit_code == 0 and sent == {"r": "+14155551234", "t": "hello"}


def test_doctor_reports_access_error(monkeypatch):
    def boom(limit=1):
        raise imessage.AccessError("no Full Disk Access")

    monkeypatch.setattr(imessage, "list_chats", boom)
    result = runner.invoke(main.app, ["doctor"])
    assert result.exit_code == 1
    assert "Full Disk Access" in result.stdout
    assert "engine:" in result.stdout


def test_doctor_reports_engine_when_up(monkeypatch):
    monkeypatch.setattr(
        imessage, "list_chats",
        lambda limit=1: [imessage.Chat(1, "chat1", "Chat One", "iMessage")],
    )
    result = runner.invoke(main.app, ["doctor"])
    assert result.exit_code == 0
    assert "engine:" in result.stdout
    assert "chat.db readable" in result.stdout


def test_read_access_error_exits_nonzero(monkeypatch):
    def boom(**kwargs):
        raise imessage.AccessError("denied")

    monkeypatch.setattr(imessage, "read_messages", boom)
    result = runner.invoke(main.app, ["read"])
    assert result.exit_code == 1
