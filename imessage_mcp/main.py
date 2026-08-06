"""Typer app for the `imsg` CLI.

Thin operator surface over imessage_mcp.imessage: list chats/contacts, read and
search messages, send, and a `doctor` that diagnoses Full Disk Access. Every
command renders via imessage_mcp.ui and exits non-zero on failure.

Agent tip: run `imsg -h` then `imsg <command> -h` for options, args, and examples.
"""
from __future__ import annotations

import json

import typer

from imessage_mcp import __version__, agent, imessage, ui

# Leading \b tells Click not to rewrap this paragraph (keeps examples agent-readable).
_APP_EPILOG = """
\b
Agent-friendly discovery:
  imsg -h                 list commands
  imsg help               agent usage sheet
  imsg <command> -h       options, args, and examples for one command
  imsg contacts -h        list / filter handles for read/send
  imsg doctor             verify Full Disk Access + engine
Examples:
  imsg contacts --limit 50
  imsg contacts -q 415
  imsg read -c +14155551234 --limit 20
  imsg search "dinner" --limit 10
  imsg attachments -c +14155551234 --kind image
  imsg download -c +14155551234 -k image -o ~/Desktop/media
  imsg send +14155551234 "on my way"
"""

app = typer.Typer(
    name="imsg",
    help=(
        "Read, search, and send iMessage from your terminal (local, macOS). "
        "Also exposed as MCP via `imsg-mcp`."
    ),
    epilog=_APP_EPILOG,
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    # None = classic Click help (preserves epilog newlines for agents).
    rich_markup_mode=None,
)


def _fail(msg: str) -> None:
    ui.console.print(ui.error_panel(msg))
    raise typer.Exit(code=1)


_AGENT_HELP = """imsg — local iMessage CLI (+ MCP via imsg-mcp)

Discover:
  imsg -h                 list commands
  imsg help               this agent-oriented usage sheet
  imsg <command> -h       options, args, and examples

Commands:
  doctor                  check Full Disk Access + engine (rust/python)
  chats [-n N]            recent conversations (use id with read --chat)
  contacts [-n N] [-q Q]  contact handles; filter with -q (phone/email substring)
  read [-c HANDLE] [--chat ID] [-n N]
                          recent messages (handles from contacts)
  search QUERY [-n N]     full-history search (incl. rich-text blobs)
  attachments [-c H] [--chat ID] [-k KIND] [-n N]
                          list media/file attachments with on-disk paths
  download -o DIR [-c H] [--chat ID] [-k KIND] [-n N]
                          copy media/audio/video/files out to DIR
  send RECIPIENT TEXT     send via Messages.app (side effect)
  version                 print package version

Examples:
  imsg contacts --limit 50
  imsg contacts -q 415
  imsg read -c +14155551234 --limit 20
  imsg read --chat 42
  imsg search "dinner" --limit 10
  imsg attachments -c +14155551234 --kind image
  imsg download -c +14155551234 -k image -o ~/Desktop/media
  imsg send +14155551234 "on my way"

KIND is a mime-type prefix: image, audio, video, application.

MCP tools: check_access, list_chats, list_contacts, get_recent_messages,
           search_messages, list_attachments, download_attachments, send_message
"""


@app.command("help")
def help_cmd(
    command: str | None = typer.Argument(
        None,
        help="Optional command name to show `imsg <command> -h` for.",
    ),
) -> None:
    """Print agent-oriented usage (or delegate to `imsg <command> -h`)."""
    if command:
        import click
        from typer.main import get_command

        click_app = get_command(app)
        with click.Context(click_app, info_name="imsg") as ctx:
            sub = click_app.get_command(ctx, command)
            if sub is None:
                _fail(
                    f"unknown command: {command!r}. "
                    f"Known: {', '.join(sorted(click_app.list_commands(ctx)))}"
                )
            with click.Context(sub, info_name=command, parent=ctx) as sub_ctx:
                typer.echo(sub.get_help(sub_ctx))
        return
    typer.echo(_AGENT_HELP)


def _human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"  # pragma: no cover - unreachable, loop returns at GB


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


@app.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  imsg doctor\n\n"
        "Exit 0 when chat.db is readable; exit 1 when Full Disk Access is missing."
    ),
)
def doctor() -> None:
    """Check Full Disk Access, print the active engine (rust/python), and guide fixes."""
    from imessage_mcp import HAVE_RUST

    ui.console.print(ui.banner())
    engine = "rust" if HAVE_RUST else "python"
    ui.console.print(ui.badge("up" if HAVE_RUST else "warn"), f"engine: {engine}")
    try:
        chats = imessage.list_chats(limit=1)
        ui.console.print(ui.badge("up"), f"chat.db readable at {imessage.db_path()}")
        ui.console.print(ui.badge("up" if chats else "warn"), f"found {len(chats)} recent chat(s)")
    except imessage.AccessError as exc:
        ui.console.print(ui.badge("down"), "chat.db not readable")
        _fail(
            f"{exc}\n\nFix: System Settings -> Privacy & Security -> Full Disk "
            "Access -> add your terminal (and Cursor, for MCP), then fully quit "
            "and reopen it."
        )


@app.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  imsg chats\n"
        "  imsg chats --limit 50\n\n"
        "Use the `id` column with `imsg read --chat <id>`."
    ),
)
def chats(
    limit: int = typer.Option(
        20,
        "--limit",
        "-n",
        help="Max conversations to list (most-recently-active first).",
        min=1,
    ),
) -> None:
    """List recent conversations with chat ids, identifiers, names, and service."""
    try:
        rows = imessage.list_chats(limit=limit)
    except imessage.AccessError as exc:
        _fail(str(exc))
    if not rows:
        ui.console.print("(no chats)")
        return
    table = ui.styled_table("Chats", ["id", "identifier", "name", "service"])
    for c in rows:
        table.add_row(str(c.chat_id), c.identifier, c.name or "", c.service or "")
    ui.console.print(table)


@app.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  imsg contacts\n"
        "  imsg contacts --limit 200\n"
        "  imsg contacts -q 415\n"
        "  imsg contacts -q @example.com\n\n"
        "Use a handle with `imsg read -c <handle>` or `imsg send <handle> \"...\"`.\n"
        "MCP equivalent: tool `list_contacts`."
    ),
)
def contacts(
    limit: int = typer.Option(
        100,
        "--limit",
        "-n",
        help="Max handles to list.",
        min=1,
    ),
    query: str | None = typer.Option(
        None,
        "--query",
        "-q",
        help="Substring filter on handle (phone/email), case-insensitive.",
    ),
) -> None:
    """List contact handles (phone numbers / emails) seen in the message store."""
    try:
        rows = imessage.list_contacts(limit=limit, query=query)
    except imessage.AccessError as exc:
        _fail(str(exc))
    if not rows:
        ui.console.print("(no contacts)" if not query else f"(no contacts matching {query!r})")
        return
    table = ui.styled_table("Contacts", ["handle", "service"])
    for c in rows:
        table.add_row(c.handle, c.service or "")
    ui.console.print(table)
    ui.console.print(
        f"[dim]{len(rows)} handle(s)"
        + (f" matching {query!r}" if query else "")
        + " — use with: imsg read -c <handle> | imsg send <handle> \"text\"[/dim]"
    )


@app.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  imsg read --limit 20\n"
        "  imsg read -c +14155551234\n"
        "  imsg read --chat 42 --limit 100\n\n"
        "Get handles via `imsg contacts`; chat ids via `imsg chats`."
    ),
)
def read(
    contact: str | None = typer.Option(
        None,
        "--contact",
        "-c",
        help="Filter by contact handle (phone or email from `imsg contacts`).",
    ),
    chat_id: int | None = typer.Option(
        None,
        "--chat",
        help="Filter by chat id (from `imsg chats`).",
    ),
    limit: int = typer.Option(
        20,
        "--limit",
        "-n",
        help="Max messages to show.",
        min=1,
    ),
) -> None:
    """Show recent messages, optionally filtered by contact handle or chat id."""
    try:
        msgs = imessage.read_messages(contact=contact, chat_id=chat_id, limit=limit)
    except imessage.AccessError as exc:
        _fail(str(exc))
    _render_messages(msgs)


@app.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  imsg search dinner\n"
        "  imsg search \"on my way\" --limit 50\n\n"
        "Also matches rich-text messages stored only in attributedBody blobs."
    ),
)
def search(
    query: str = typer.Argument(..., help="Text to search for in message bodies."),
    limit: int = typer.Option(
        20,
        "--limit",
        "-n",
        help="Max results (newest first).",
        min=1,
    ),
) -> None:
    """Search the full history (including rich-text messages), newest first."""
    try:
        msgs = imessage.search_all(query, limit=limit)
    except imessage.AccessError as exc:
        _fail(str(exc))
    _render_messages(msgs)


@app.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  imsg send +14155551234 \"on my way\"\n"
        "  imsg send someone@example.com \"ping\"\n\n"
        "Side effect: delivers a real message via Messages.app.\n"
        "Pick a recipient from `imsg contacts`."
    ),
)
def send(
    recipient: str = typer.Argument(
        ...,
        help="Destination handle: phone number or email (see `imsg contacts`).",
    ),
    text: str = typer.Argument(..., help="Message body to send."),
) -> None:
    """Send an iMessage/SMS to a handle (phone number or email)."""
    try:
        imessage.send_message(recipient, text)
    except (ValueError, RuntimeError) as exc:
        _fail(str(exc))
    ui.console.print(ui.badge("sent"), f"to {recipient}")


@app.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  imsg attachments -c +14155551234\n"
        "  imsg attachments --chat 42 --kind image\n"
        "  imsg attachments --kind audio --limit 50\n\n"
        "Lists media/files only; use `imsg download` to copy them out.\n"
        "MCP equivalent: tool `list_attachments`."
    ),
)
def attachments(
    contact: str | None = typer.Option(
        None,
        "--contact",
        "-c",
        help="Filter by contact handle (phone or email from `imsg contacts`).",
    ),
    chat_id: int | None = typer.Option(
        None,
        "--chat",
        help="Filter by chat id (from `imsg chats`).",
    ),
    kind: str | None = typer.Option(
        None,
        "--kind",
        "-k",
        help="Filter by mime-type prefix: image, audio, video, application.",
    ),
    limit: int = typer.Option(
        20,
        "--limit",
        "-n",
        help="Max attachments to list (newest first).",
        min=1,
    ),
) -> None:
    """List media/file attachments (images, audio, video) with their paths."""
    try:
        rows = imessage.list_attachments(
            contact=contact, chat_id=chat_id, limit=limit, kind=kind
        )
    except imessage.AccessError as exc:
        _fail(str(exc))
    if not rows:
        ui.console.print("(no attachments)")
        return
    table = ui.styled_table(
        "Attachments", ["when", "from", "name", "type", "size", "path"]
    )
    for a in rows:
        table.add_row(
            a.date or "?",
            "me" if a.is_from_me else a.sender,
            a.transfer_name,
            a.mime_type or "?",
            _human_bytes(a.total_bytes),
            a.filename if a.exists else f"{a.filename} (missing)",
        )
    ui.console.print(table)
    missing = sum(1 for a in rows if not a.exists)
    ui.console.print(
        f"[dim]{len(rows)} attachment(s)"
        + (f", {missing} not on disk (iCloud-only or pruned)" if missing else "")
        + " — copy with: imsg download -o <dir>[/dim]"
    )


@app.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  imsg download -c +14155551234 -o ~/Desktop/media\n"
        "  imsg download --chat 42 --kind image -o ./photos\n"
        "  imsg download --kind audio -n 50 -o ./voice-memos\n\n"
        "Copies from ~/Library/Messages/Attachments — nothing is fetched over\n"
        "the network. Existing files are never overwritten (names get -1, -2).\n"
        "MCP equivalent: tool `download_attachments`."
    ),
)
def download(
    out: str = typer.Option(
        ...,
        "--out",
        "-o",
        help="Destination directory (created if missing).",
    ),
    contact: str | None = typer.Option(
        None,
        "--contact",
        "-c",
        help="Filter by contact handle (phone or email from `imsg contacts`).",
    ),
    chat_id: int | None = typer.Option(
        None,
        "--chat",
        help="Filter by chat id (from `imsg chats`).",
    ),
    kind: str | None = typer.Option(
        None,
        "--kind",
        "-k",
        help="Filter by mime-type prefix: image, audio, video, application.",
    ),
    limit: int = typer.Option(
        20,
        "--limit",
        "-n",
        help="Max attachments to copy (newest first).",
        min=1,
    ),
) -> None:
    """Download media/attachments (images, audio, video, files) to a folder."""
    try:
        saved = imessage.download_attachments(
            out, contact=contact, chat_id=chat_id, limit=limit, kind=kind
        )
    except imessage.AccessError as exc:
        _fail(str(exc))
    except ValueError as exc:
        _fail(str(exc))
    if not saved:
        ui.console.print("(nothing downloaded — no matching attachments on disk)")
        return
    for p in saved:
        ui.console.print(ui.badge("sent"), str(p))
    ui.console.print(f"[dim]{len(saved)} file(s) -> {out}[/dim]")


@app.command(epilog="\b\nExample:\n  imsg version")
def version() -> None:
    """Print the installed package version."""
    ui.console.print(f"imsg {__version__}")


agent_app = typer.Typer(
    name="agent",
    help="Machine-readable schema and playbook for LLM/automation use.",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
app.add_typer(agent_app, name="agent")


@agent_app.command("schema")
def agent_schema_cmd() -> None:
    """Print JSON schema of every stable command + params."""
    typer.echo(json.dumps(agent.build_schema(), indent=2))


@agent_app.command("guide")
def agent_guide_cmd() -> None:
    """Print a short markdown playbook for LLM agents."""
    typer.echo(agent.build_guide(), nl=False)


if __name__ == "__main__":  # pragma: no cover
    app()
