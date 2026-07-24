"""imsg: fast, local iMessage access (Rust-accelerated) with CLI + MCP server."""

__version__ = "0.1.2"

# True when the compiled Rust core (imsgcore) is importable; the pure-Python
# path in imessage.py is used otherwise. Exposed so `imsg doctor` / benchmarks
# can report which engine is active.
try:  # pragma: no cover - presence depends on build
    import imsgcore  # noqa: F401

    HAVE_RUST = True
except ImportError:  # pragma: no cover
    HAVE_RUST = False
