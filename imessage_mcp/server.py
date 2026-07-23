"""MCP server exposing local iMessage read/search/send over stdio.

Uses FastMCP (from the `mcp` package). All read tools open chat.db read-only;
`send` is the only tool with a side effect. Run via the `imsg-mcp` entry point
or `python -m imessage_mcp.server`.

CLI twin: `imsg` (`imsg -h`, `imsg contacts -h`, …).
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from imessage_mcp import HAVE_RUST, imessage

mcp = FastMCP("imsg")


@mcp.tool()
def check_access() -> str:
    """Diagnose whether chat.db is readable (Full Disk Access) and which engine
    (Rust or pure-Python) is active. Run this first if other tools fail."""
    engine = "rust" if HAVE_RUST else "python"
    try:
        n = len(imessage.list_chats(limit=1))
        return f"ok: chat.db readable ({engine} engine); {n} chat(s) reachable"
    except imessage.AccessError as exc:
        return f"error: {exc}"


@mcp.tool()
def get_recent_messages(
    contact: str | None = None,
    chat_id: int | None = None,
    limit: int = 20,
) -> list[dict]:
    """Recent messages, optionally filtered by contact handle or chat id.

    Use `list_contacts` to discover handles and `list_chats` for chat ids.
    """
    return [
        m.dict()
        for m in imessage.read_messages(contact=contact, chat_id=chat_id, limit=limit)
    ]


@mcp.tool()
def search_messages(query: str, limit: int = 20) -> list[dict]:
    """Search the full history for `query`, newest first — including rich-text
    messages stored as attributedBody blobs that plain text search misses."""
    return [m.dict() for m in imessage.search_all(query, limit=limit)]


@mcp.tool()
def list_chats(limit: int = 20) -> list[dict]:
    """List recent conversations with their chat ids (for `get_recent_messages`)."""
    return [c.dict() for c in imessage.list_chats(limit=limit)]


@mcp.tool()
def list_contacts(limit: int = 100, query: str | None = None) -> list[dict]:
    """List contact handles (phone numbers / emails) from the message store.

    Optional `query` substring-filters handles (case-insensitive), e.g. \"415\"
    or \"@example.com\". Use returned handles with `get_recent_messages(contact=...)`
    or `send_message(recipient=...)`.
    """
    return [c.dict() for c in imessage.list_contacts(limit=limit, query=query)]


@mcp.tool()
def send_message(recipient: str, text: str) -> str:
    """Send an iMessage/SMS to a handle (phone number or email). Has a side
    effect: delivers a real message via Messages.app. Prefer a handle from
    `list_contacts`."""
    imessage.send_message(recipient, text)
    return f"sent to {recipient}"


def main() -> None:
    """Entry point for the `imsg-mcp` script; serves over stdio."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
