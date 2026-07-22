# imsg — fast, local iMessage for your terminal & MCP

[![PyPI](https://img.shields.io/pypi/v/imsg.svg)](https://pypi.org/project/imsg/)
[![Python](https://img.shields.io/pypi/pyversions/imsg.svg)](https://pypi.org/project/imsg/)
[![Built with Rust](https://img.shields.io/badge/core-Rust-orange.svg)](rust/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![macOS only](https://img.shields.io/badge/os-macOS-black.svg)](#requirements)

Read, search, and send iMessage from your terminal — or expose it to Claude,
Cursor, VS Code, or any MCP client. Everything runs **locally on your Mac**:
no cloud, no login, no account. Reads open `~/Library/Messages/chat.db`
**read-only**; sends go through Messages.app.

**Why another one?** The hot path — decoding tens of thousands of
`attributedBody` typedstream blobs — is written in **Rust** (PyO3 + rusqlite),
so reads and searches over a large history are several times faster than the
pure-Python equivalent that other Messages servers use. Pure Python still ships
as a zero-dependency fallback, so it works even where the wheel doesn't.

<!-- BENCH -->
### Benchmark

Full-history search over a synthetic **50,000-message** database (70% stored as
`attributedBody` blobs), best-of-5, Apple Silicon (16 cores):

| operation | pure-Python | Rust core | speedup |
|---|---:|---:|---:|
| **full-history search** (decodes every message) | 120.9 ms | **35.7 ms** | **3.4×** |
| batched blob decode (allocation-bound) | 19.1 ms | 19.6 ms | 1.0× |

Two honest caveats, stated up front:
- Raw blob decoding is ~a wash — it's bound by allocating result strings, not
  CPU, so native code doesn't help. The win is in **search**, where Rust
  decodes and filters across all cores and returns only the matches.
- It's 3.4×, not 16×, because the SQLite read and result marshalling are serial
  on both sides; only the decode+match parallelizes. The gap widens on larger
  histories.

Reproduce: `python bench/benchmark.py`. **Bonus:** this search also finds
messages whose text lives in an `attributedBody` blob — which a plain
`text LIKE` query (used by Python-only Messages servers) silently misses.
<!-- /BENCH -->

## Install

```bash
# with uv (recommended) — provisions Python + the prebuilt wheel
uv tool install imsg

# or pip
pip install imsg

# or Homebrew
brew install ml-lubich/tap/imsg
```

## Requirements

- **macOS** (reads the local Messages database; sends via Messages.app).
- **Full Disk Access** for the app that runs `imsg` — Terminal/iTerm/Ghostty
  for the CLI, or your MCP client (Claude Desktop, Cursor, VS Code…) for the
  server. System Settings → Privacy & Security → Full Disk Access → add it,
  then fully quit and reopen it.
- Messages.app signed in and able to send a normal message.

Run `imsg doctor` to check access and see which engine (Rust or Python) is live.

## CLI

```bash
imsg doctor                       # check Full Disk Access + engine
imsg chats                        # recent conversations + their ids
imsg contacts                     # handles (numbers / emails) seen
imsg read -c +14155551234         # recent messages with a contact
imsg read --chat 42 --limit 100   # a specific conversation
imsg search "dinner"              # search message text
imsg send +14155551234 "on my way"
```

## MCP server

The `imsg-mcp` entry point speaks MCP over stdio. Add it to any client:

**Claude Code**
```bash
claude mcp add --transport stdio --scope user imsg -- imsg-mcp
```

**Claude Desktop / Cursor** (`mcpServers`) · **VS Code** (`servers`):
```json
{ "mcpServers": { "imsg": { "command": "imsg-mcp" } } }
```

Tools exposed: `check_access`, `get_recent_messages`, `search_messages`,
`list_chats`, `list_contacts`, `send_message` (the only one with a side effect).

## How it works

There is no official iMessage API. Every tool in this space does the same two
local things; `imsg` just does the heavy half in Rust:

| Operation | Mechanism | Engine |
|---|---|---|
| read / search / list | `chat.db` (SQLite, read-only) + typedstream decode | **Rust** (`imsgcore`), Python fallback |
| send | AppleScript → Messages.app | Python (`osascript`) |

SQLite is the same C library everywhere, so the read speedup comes from doing
the per-message `attributedBody` decode and row marshalling natively instead of
in a Python loop. See [`bench/benchmark.py`](bench/benchmark.py) for the
methodology — both engines run identical queries over an identical synthetic
database, and the pure-Python column is the same algorithm Python-only servers
use.

## Privacy & security

- All database connections are opened **read-only** (`mode=ro`).
- Nothing is uploaded, mirrored, or indexed off-device.
- Sending is isolated in one function, escapes its AppleScript inputs, and is
  the only operation that writes anything anywhere.
- Full Disk Access is broad — grant it only to apps you trust.

## Development

```bash
git clone https://github.com/ml-lubich/imsg.git && cd imsg
uv venv && source .venv/bin/activate
uv pip install maturin
maturin develop            # builds the Rust core + installs the package
uv pip install -e ".[dev]"
pytest                     # tests run on the pure-Python path (and Rust if built)
python bench/benchmark.py  # regenerate the benchmark
```

## License

MIT © ml-lubich. Not affiliated with Apple. Use responsibly and only with
accounts and conversations you own.
