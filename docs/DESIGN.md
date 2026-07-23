# Design

## CLI surface

Every command supports `-h` and `--help` (options, args, examples). Agents
should start with `imsg help` or `imsg -h`, then `imsg <command> -h`.

| Command | Purpose |
|---|---|
| `help` | Agent-oriented usage sheet (`imsg help [command]`) |
| `doctor` | FDA check + active engine (rust/python) |
| `chats` | Recent conversations (`-n/--limit`) |
| `contacts` | Handles seen in the store (`-n/--limit`, `-q/--query`) |
| `read` | Recent messages (`-c/--contact`, `--chat`, `-n/--limit`) |
| `search` | Full-history text search (incl. rich text) |
| `send` | Deliver via Messages.app |
| `version` | Print package version |

`contacts` prints handles for use with `read -c` / `send`. Output uses Rich
tables/panels; failures exit non-zero with an error panel.

## MCP tools

| Tool | Side effect |
|---|---|
| `check_access` | none |
| `get_recent_messages` | none |
| `search_messages` | none |
| `list_chats` | none |
| `list_contacts` (`limit`, optional `query`) | none |
| `send_message` | yes — real message |

## Cursor / client config

```json
{ "mcpServers": { "imsg": { "command": "imsg-mcp" } } }
```

Grant Full Disk Access to the MCP host app, then fully quit and reopen it.
