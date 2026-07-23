# API

Public surfaces are the CLI and MCP tools. Python callers import
`imessage_mcp.imessage`.

## Core (`imessage_mcp.imessage`)

| Function | Notes |
|---|---|
| `db_path()` | `IMESSAGE_DB` override for tests |
| `list_chats(limit)` | Recent chats |
| `list_contacts(limit, query=)` | Handles; optional case-insensitive substring filter |
| `read_messages(contact=, chat_id=, limit=)` | Recent messages |
| `search_all(query, limit)` | Full-history search |
| `send_message(recipient, text)` | AppleScript send |

Raises `AccessError` when `chat.db` is missing or unreadable (typically missing
Full Disk Access).

## CLI entry points

```
imsg = imessage_mcp.main:app
imsg-mcp = imessage_mcp.server:main
```

## MCP

Stdio FastMCP server named `imsg`. See `docs/DESIGN.md` for tool list.
