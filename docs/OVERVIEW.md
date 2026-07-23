# Overview

`imsg` is a local macOS tool that reads/searches iMessage history and can send
messages. It ships as:

- **CLI** — `imsg` (doctor, chats, contacts, read, search, send, version)
- **MCP server** — `imsg-mcp` (stdio) for Claude, Cursor, VS Code, etc.

Everything stays on-device. Reads open `~/Library/Messages/chat.db` read-only;
sends go through Messages.app via AppleScript.

## Install

```bash
uv tool install imsg          # recommended
pip install imsg
brew install ml-lubich/tap/imsg
```

## Requirements

- macOS with Messages signed in
- **Full Disk Access** for the host process (Terminal for CLI; Cursor/Claude for MCP)
- Automation permission for Messages.app on first send

Verify with `imsg doctor`.
