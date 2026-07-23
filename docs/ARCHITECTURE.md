# Architecture

## Layers

| Layer | Role | Location |
|---|---|---|
| CLI | Typer commands, Rich UI | `imessage_mcp/main.py`, `ui.py` |
| MCP | FastMCP stdio tools | `imessage_mcp/server.py` |
| Domain/IO | chat.db read + AppleScript send | `imessage_mcp/imessage.py` |
| Native core | Parallel typedstream decode + search | `rust/` → `imsgcore` |

## Data flow

```
CLI / MCP tools
      │
      ▼
imessage.py  ──read──►  chat.db (SQLite, mode=ro)
      │                    └─ Rust path (imsgcore) when built
      └──send──►  osascript → Messages.app
```

## Engine selection

`HAVE_RUST` is set at import time. If `imsgcore` is importable, read/search use
the Rust core; otherwise pure Python falls back automatically.

## Decision records

- **Local-only**: no cloud, no bridge daemon (contrast WhatsApp MCP patterns).
- **Rust hot path**: decode/filter `attributedBody` blobs in parallel; Python
  remains the packaging + MCP/CLI surface.
- **Single send path**: AppleScript only; isolated and escaped.
