# Requirements

## User stories

- As a macOS user, I can list chats/contacts and read/search messages from the terminal.
- As an agent, I can discover CLI usage via `imsg -h` and `imsg <command> -h` (options, args, examples).
- As an agent host (Cursor/Claude), I can call the same capabilities over MCP stdio, including `list_contacts`.
- As a user, I can send a message via Messages.app when I explicitly invoke send.
- As an operator, `imsg doctor` tells me whether FDA works and which engine is live.

## Hard constraints

- macOS only
- `chat.db` opened read-only (`mode=ro`)
- No cloud upload / off-device index
- Send is the only side-effecting operation
- Full Disk Access required for reads; Automation for send

## Non-goals

- Cross-platform Messages access
- Cloud sync or multi-device bridging
- Replacing Messages.app UI
