# Testing

## Strategy

- Unit/smoke tests use a synthetic SQLite fixture (`IMESSAGE_DB`) — no live
  Messages database required.
- CLI tests use Typer `CliRunner` with monkeypatched core functions.
- Search tests cover attributedBody (rich-text) messages when Rust is built.

## Commands

```bash
uv pip install -e ".[dev]"
pytest
python bench/benchmark.py   # optional performance
```

## Definition of done

1. Feature under test has an explicit passing test
2. `pytest` green (pure-Python path always; Rust path when `imsgcore` built)
3. Manual smoke when touching access/FDA: `imsg doctor`
4. MCP smoke: initialize JSON-RPC over stdio to `imsg-mcp`
