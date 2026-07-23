# Deployment

## Distribution channels

1. **PyPI** — `pip install mac-imsg` / `uv tool install mac-imsg` (CLIs remain `imsg` / `imsg-mcp`; the `imsg` name is blocked on PyPI as too similar to another project)
2. **Homebrew** — `brew install ml-lubich/tap/imsg` (formula in `homebrew-tap`)
3. **From source** — `maturin develop` + `uv pip install -e ".[dev]"`

## Release checklist

1. Bump `version` in `pyproject.toml` and `imessage_mcp/__init__.py`
2. Build/publish wheel+sdist (maturin / PyPI)
3. Tag `vX.Y.Z` and attach sdist for Homebrew `url`/`sha256`
4. Update `homebrew-tap/Formula/imsg.rb` resources if deps changed
5. Smoke: `imsg version`, `imsg doctor`, MCP initialize handshake

## Runtime hosts

| Host | Entry point | FDA target |
|---|---|---|
| Terminal / iTerm / Ghostty | `imsg` | that terminal app |
| Cursor | `imsg-mcp` | Cursor.app |
| Claude Desktop / Code | `imsg-mcp` | that app |
