# Plan: agent-friendly CLI help + contacts visibility

## Will NOT Change
- MCP tool names (`list_contacts` stays)
- Rust search/decode hot path
- Send semantics

## Drift Risks
- Over-long help text — keep examples short
- Query filter must work on both Rust and Python contact paths

## Verification Plan
- [ ] `imsg -h` and `imsg <cmd> -h` succeed for every command
- [ ] `imsg contacts` / `imsg contacts -q` work
- [ ] MCP `list_contacts` still works (+ optional query)
- [ ] pytest green
