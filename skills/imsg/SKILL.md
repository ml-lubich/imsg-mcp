---
name: imsg
description: Read, search, and send iMessage on macOS from a CLI or MCP server. Use when a task needs to look up a chat.db history, list/search iMessage conversations or contacts, fetch attachments, or send an iMessage/SMS. Triggers include "check my messages", "search iMessage for X", "who texted me about Y", "list my iMessage contacts", "send an iMessage to X", or wiring an agent's MCP config to talk to Messages.app. macOS only — no Linux/Windows equivalent.
---

# imsg — local iMessage CLI + MCP

Reads `~/Library/Messages/chat.db` read-only (Rust core with a pure-Python
fallback) and sends through Messages.app via AppleScript. Everything runs
locally — no cloud, no login. Package name: `imsg-mcp`; binaries: `imsg`
(CLI) and `imsg-mcp` (MCP server over stdio).

## Install

```bash
# from this checkout
uv tool install -e ~/dev/imsg-mcp

# from a fresh clone
git clone https://github.com/ml-lubich/imsg-mcp && uv tool install -e ./imsg-mcp
```

Installs both `imsg` and `imsg-mcp` on PATH. The Rust extension
(`imsgcore/imsgcore.abi3.so`) ships prebuilt in the repo; if it fails to
import for the target Python/arch, `imessage_mcp` falls back to a pure-Python
decoder automatically — same behavior, slower on large histories.

## CLI commands

Run `imsg -h` or `imsg <command> -h` for full help; flags below are real,
copied from `--help`.

- `imsg doctor` — check Full Disk Access + which engine (Rust/Python) is active. Run this first.
- `imsg chats` — list recent conversations with chat ids/identifiers.
- `imsg contacts [-n/--limit N] [-q/--query STR]` — list handles seen in the store, plus AddressBook name matches for `-q`.
- `imsg read [-c/--contact HANDLE] [--limit N]` — recent messages, optionally filtered.
- `imsg search QUERY [-n/--limit N]` — full-history search, including rich-text (`attributedBody`) messages.
- `imsg send RECIPIENT TEXT` — send via Messages.app. `RECIPIENT` is a handle or a contact name that resolves to exactly one person; ambiguous names error out, nothing sent.
- `imsg attachments [-c HANDLE] [--kind image|video|audio|file]` — list media with metadata.
- `imsg download [-c HANDLE] [-k KIND] [-o DIR]` — download attachments to a directory.
- `imsg agent` — machine-readable schema/playbook for LLM callers.
- `imsg version` — installed package version.

## MCP server

```bash
imsg-mcp
```

Runs FastMCP over stdio (blocking; no `--help`/flags). 8 tools: `check_access`,
`get_recent_messages`, `search_messages`, `list_chats`, `list_contacts`,
`list_attachments`, `download_attachments`, `send_message`.

Claude Code:

```bash
claude mcp add imsg -- imsg-mcp
```

Or point a client's MCP config at the same command (`command: "imsg-mcp"`,
no args, stdio transport).

## macOS permissions

- **Full Disk Access** (System Settings -> Privacy & Security -> Full Disk
  Access) for the terminal/app running `imsg`/`imsg-mcp` — required to open
  `chat.db` and the AddressBook SQLite store under `~/Library`.
- **Automation permission for Messages.app** — requested by macOS the first
  time `send`/`send_message` runs an AppleScript `tell application "Messages"`.
  Only the send path triggers this; every read tool is Full Disk Access only.

Harmless read that triggers the Full Disk Access prompt without sending or
mutating anything:

```bash
imsg doctor
```

## Safety rules

- Read-only by default: `check_access`, `get_recent_messages`,
  `search_messages`, `list_chats`, `list_contacts`, `list_attachments`,
  `download_attachments` never write to chat.db or Messages.app.
- `send`/`send_message` is the only tool with a side effect (delivers a real
  message). Only call it when the user explicitly asks to send something,
  with an explicit recipient and text — never send speculatively or as part
  of a "just checking" flow.
- Never delete or modify chat.db, AddressBook stores, or Messages.app data.
- A name passed to `send` must resolve to exactly one AddressBook contact; if
  ambiguous or unmatched, it errors instead of guessing.
