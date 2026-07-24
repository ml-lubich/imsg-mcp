"""Agent discovery: JSON command schemas for LLM/automation use."""
from __future__ import annotations

from typing import Any


def build_schema() -> dict[str, Any]:
    return {
        "version": "0.1.2",
        "tool": "imsg",
        "mcp": "imsg-mcp",
        "help": "imsg -h | imsg <cmd> -h | imsg agent schema",
        "commands": [
            {
                "name": "doctor",
                "help": "Check Full Disk Access + engine",
                "params": [],
            },
            {
                "name": "chats",
                "help": "List recent conversations",
                "params": [
                    {"name": "limit", "type": "int", "required": False, "flags": ["-n", "--limit"]}
                ],
            },
            {
                "name": "contacts",
                "help": "List/filter handles",
                "params": [
                    {"name": "limit", "type": "int", "required": False, "flags": ["-n", "--limit"]},
                    {"name": "query", "type": "str", "required": False, "flags": ["-q", "--query"]},
                ],
            },
            {
                "name": "read",
                "help": "Recent messages",
                "params": [
                    {"name": "contact", "type": "str", "required": False, "flags": ["-c", "--contact"]},
                    {"name": "chat", "type": "int", "required": False, "flags": ["--chat"]},
                    {"name": "limit", "type": "int", "required": False, "flags": ["-n", "--limit"]},
                ],
            },
            {
                "name": "search",
                "help": "Full-history search",
                "params": [
                    {"name": "query", "type": "str", "required": True, "flags": []},
                    {"name": "limit", "type": "int", "required": False, "flags": ["-n", "--limit"]},
                ],
            },
            {
                "name": "send",
                "help": "Send iMessage/SMS (side effect)",
                "params": [
                    {"name": "recipient", "type": "str", "required": True, "flags": []},
                    {"name": "text", "type": "str", "required": True, "flags": []},
                ],
            },
            {"name": "version", "help": "Print version", "params": []},
            {"name": "help", "help": "Agent usage sheet", "params": []},
            {"name": "agent schema", "help": "This JSON schema", "params": []},
            {"name": "agent guide", "help": "Markdown playbook", "params": []},
        ],
    }


def build_guide() -> str:
    return """# imsg agent guide

Prefer CLI over MCP for simple reads (saves tokens).

```
imsg -h
imsg <command> -h
imsg agent schema
imsg doctor
imsg read -c +1… --limit 20
imsg send +1… "text"   # only when user asks
```

No unsolicited digests. macOS only. Full Disk Access required for read/search.
"""
