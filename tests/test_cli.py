"""CLI smoke tests via typer's CliRunner, with core functions monkeypatched."""
from __future__ import annotations

from typer.testing import CliRunner

from imessage_mcp import imessage, main

runner = CliRunner()


def test_version():
    result = runner.invoke(main.app, ["version"])
    assert result.exit_code == 0 and "imsg" in result.stdout


def test_chats_renders(monkeypatch):
    monkeypatch.setattr(
        imessage, "list_chats",
        lambda limit=20: [imessage.Chat(1, "chat1", "Chat One", "iMessage")],
    )
    result = runner.invoke(main.app, ["chats"])
    assert result.exit_code == 0 and "chat1" in result.stdout


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
    assert result.exit_code == 1 and "Full Disk Access" in result.stdout


def test_read_access_error_exits_nonzero(monkeypatch):
    def boom(**kwargs):
        raise imessage.AccessError("denied")

    monkeypatch.setattr(imessage, "read_messages", boom)
    result = runner.invoke(main.app, ["read"])
    assert result.exit_code == 1
