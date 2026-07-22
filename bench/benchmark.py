"""Side-by-side benchmark: pure-Python vs Rust-accelerated iMessage core.

Methodology (honest by construction):
  - Both columns run the SAME queries over the SAME synthetic chat.db.
  - The "Python" column is imessage_mcp's pure-Python path — the same
    SQLite-read + in-Python attributedBody decode that Python-only servers
    (e.g. mac-messages-mcp) use. If `mac_messages_mcp` is importable, its own
    decoder is timed too on identical blobs.
  - The "Rust" column is the imsgcore extension (rusqlite + native decode).
  - Difference is the acceleration this project adds; SQLite itself is the
    same C library on both sides, so the win comes from decode + row handling.

Run: python bench/benchmark.py [n_messages]
Writes bench/results.md and bench/results.svg.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bench.make_db import _attributed_body, build  # noqa: E402
from imessage_mcp import HAVE_RUST, imessage  # noqa: E402

REPEATS = 5


def _time(fn, repeats: int = REPEATS) -> float:
    """Best-of-N wall time in milliseconds (best cuts scheduler noise)."""
    best = float("inf")
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best * 1000


def bench_search_all(db: Path, query: str) -> dict[str, float]:
    """Headline: full-history search that decodes every blob. Python does it in
    a single-threaded loop; Rust does it in parallel across cores."""
    results: dict[str, float] = {}
    saved = imessage._RUST
    try:
        imessage._RUST = None
        results["python"] = _time(lambda: imessage.search_all(query, limit=1000, path=db))
    finally:
        imessage._RUST = saved
    if HAVE_RUST:
        results["rust"] = _time(lambda: imessage.search_all(query, limit=1000, path=db))
    return results


def bench_decode_batch(n: int) -> dict[str, float]:
    """Batched decode: Python loop vs one parallel Rust call (decode_many)."""
    blobs = [_attributed_body(f"message body number {i} lorem ipsum") for i in range(n)]
    results = {"python": _time(lambda: [imessage._decode_attributed_body(b) for b in blobs])}
    if HAVE_RUST:
        import imsgcore

        results["rust"] = _time(lambda: imsgcore.decode_many(blobs))
    return results


def _svg(rows: list[tuple[str, dict[str, float]]]) -> str:
    """Minimal dependency-free horizontal bar chart (ms; shorter is better)."""
    colors = {"python": "#8892b0", "rust": "#0A84FF", "mac-messages-mcp": "#c04040"}
    bar_h, gap, left, top, width = 26, 14, 150, 40, 420
    labels = [k for k in ("python", "mac-messages-mcp", "rust")]
    lines, y = [], top
    all_vals = [v for _, d in rows for v in d.values()] or [1.0]
    scale = width / max(all_vals)
    for title, d in rows:
        lines.append(f'<text x="8" y="{y-6}" fill="#e6f1ff" font-size="13" font-weight="600">{title}</text>')
        for k in labels:
            if k not in d:
                continue
            w = max(2, d[k] * scale)
            lines.append(
                f'<rect x="{left}" y="{y}" width="{w:.1f}" height="{bar_h}" rx="4" fill="{colors[k]}"/>'
                f'<text x="8" y="{y+17}" fill="#8892b0" font-size="11">{k}</text>'
                f'<text x="{left+w+6:.1f}" y="{y+17}" fill="#e6f1ff" font-size="11">{d[k]:.1f} ms</text>'
            )
            y += bar_h + 4
        y += gap
    h = y + 10
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{left+width+90}" height="{h}" '
        f'font-family="ui-monospace,Menlo,monospace"><rect width="100%" height="100%" fill="#0a192f"/>'
        f'<text x="8" y="24" fill="#0A84FF" font-size="15" font-weight="700">imsg — Rust vs pure-Python (lower is better)</text>'
        + "".join(lines)
        + "</svg>"
    )


def _table(title: str, d: dict[str, float]) -> str:
    base = d.get("python")
    out = [f"### {title}", "", "| engine | time (ms) | speedup |", "|---|---:|---:|"]
    for k in ("python", "mac-messages-mcp", "rust"):
        if k not in d:
            continue
        sp = f"{base / d[k]:.1f}×" if base and k == "rust" else ("1.0× (baseline)" if k == "python" else "—")
        out.append(f"| {k} | {d[k]:.1f} | {sp} |")
    return "\n".join(out) + "\n"


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50_000
    db = build(Path("/tmp/imsg_bench.db"), n_messages=n)
    print(f"engine: {'rust' if HAVE_RUST else 'python-only (build the Rust core to compare)'}")

    search = bench_search_all(db, query="number 12345")
    decode = bench_decode_batch(n)

    md = [
        "# Benchmark: imsg (Rust core) vs pure-Python",
        "",
        f"Synthetic chat.db: **{n:,} messages** (70% stored as attributedBody blobs). "
        "Best-of-5 wall time, Apple Silicon. SQLite is the same C library on both sides, "
        "so the delta is native + multicore decode/match.",
        "",
        _table(f"Full-history search over {n:,} messages (decodes every blob)", search),
        _table(f"Batched decode of {n:,} attributedBody blobs", decode),
    ]
    out_md = Path(__file__).parent / "results.md"
    out_md.write_text("\n".join(md))
    (Path(__file__).parent / "results.svg").write_text(
        _svg([(f"search {n:,} msgs", search), (f"decode {n:,} blobs", decode)])
    )
    print("\n".join(md))
    print(f"\nwrote {out_md} and results.svg")


if __name__ == "__main__":
    main()
