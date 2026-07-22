"""Typer app for the `imsg` CLI.

Thin operator surface over imessage_mcp.imessage: list chats/contacts, read and
search messages, send, and a `doctor` that diagnoses Full Disk Access. Every
command renders via imessage_mcp.ui and exits non-zero on failure.
"""
from __future__ import annotations

import typer

from imessage_mcp import __version__, imessage, ui

app = typer.Typer(
    name="imsg",
    help="Read, search, and send iMessage from your terminal (local, macOS).",
    no_args_is_help=True,
)


def _fail(msg: str) -> None:
    ui.console.print(ui.error_panel(msg))
    raise typer.Exit(code=1)


def _render_messages(msgs: list[imessage.Message]) -> None:
    if not msgs:
        ui.console.print("(no messages)")
        return
    table = ui.styled_table("Messages", ["when", "from", "text"])
    for m in msgs:
        who = "me" if m.is_from_me else m.sender
        body = m.text or ("[attachment]" if m.has_attachment else "")
        table.add_row(m.date or "?", who, body)
    ui.console.print(table)


@app.command()
def doctor() -> None:
    """Check that chat.db is readable (Full Disk Access) and print guidance."""
    ui.console.print(ui.banner())
    try:
        chats = imessage.list_chats(limit=1)
        ui.console.print(ui.badge("up"), f"chat.db readable at {imessage.db_path()}")
        ui.console.print(ui.badge("up" if chats else "warn"), f"found {len(chats)} recent chat(s)")
    except imessage.AccessError as exc:
        ui.console.print(ui.badge("down"), "chat.db not readable")
        _fail(
            f"{exc}\n\nFix: System Settings -> Privacy & Security -> Full Disk "
            "Access -> add your terminal, then fully quit and reopen it."
        )


@app.command()
def chats(limit: int = typer.Option(20, help="Max conversations to list.")) -> None:
    """List recent conversations, most-recently-active first."""
    try:
        rows = imessage.list_chats(limit=limit)
    except imessage.AccessError as exc:
        _fail(str(exc))
    table = ui.styled_table("Chats", ["id", "identifier", "name", "service"])
    for c in rows:
        table.add_row(str(c.chat_id), c.identifier, c.name or "", c.service or "")
    ui.console.print(table)


@app.command()
def contacts(limit: int = typer.Option(100, help="Max handles to list.")) -> None:
    """List handles (phone numbers / emails) seen in the message store."""
    try:
        rows = imessage.list_contacts(limit=limit)
    except imessage.AccessError as exc:
        _fail(str(exc))
    table = ui.styled_table("Contacts", ["handle", "service"])
    for c in rows:
        table.add_row(c.handle, c.service or "")
    ui.console.print(table)


@app.command()
def read(
    contact: str = typer.Option(None, "--contact", "-c", help="Filter by handle."),
    chat_id: int = typer.Option(None, "--chat", help="Filter by chat id."),
    limit: int = typer.Option(20, help="Max messages."),
) -> None:
    """Show recent messages, optionally filtered by contact or chat."""
    try:
        msgs = imessage.read_messages(contact=contact, chat_id=chat_id, limit=limit)
    except imessage.AccessError as exc:
        _fail(str(exc))
    _render_messages(msgs)


@app.command()
def search(query: str, limit: int = typer.Option(20, help="Max results.")) -> None:
    """Search the full history (incl. rich-text messages), newest first."""
    try:
        msgs = imessage.search_all(query, limit=limit)
    except imessage.AccessError as exc:
        _fail(str(exc))
    _render_messages(msgs)


@app.command()
def send(recipient: str, text: str) -> None:
    """Send an iMessage/SMS to a handle (phone number or email)."""
    try:
        imessage.send_message(recipient, text)
    except (ValueError, RuntimeError) as exc:
        _fail(str(exc))
    ui.console.print(ui.badge("sent"), f"to {recipient}")


@app.command()
def version() -> None:
    """Print the installed version."""
    ui.console.print(f"imsg {__version__}")


if __name__ == "__main__":  # pragma: no cover
    app()
