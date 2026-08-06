"""Generate a synthetic chat.db for benchmarks and tests.

Uses stdlib sqlite3 to build a schema-compatible subset of the real Messages
database. Crucially, a configurable fraction of messages store their text in an
`attributedBody` typedstream blob with `text` NULL — this is the case that
forces per-message binary decoding, i.e. the work the Rust core accelerates.

No real message data is ever touched; everything here is fabricated.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def _attributed_body(text: str) -> bytes:
    """Build a minimal typedstream-ish blob our decoder understands.

    Layout mirrors what the decoder scans for: an `NSString` marker, 5 filler
    bytes, a length byte (0x81 + 2-byte LE length when >= 128), then UTF-8.
    """
    raw = text.encode("utf-8")
    prefix = b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84NSString\x01\x94\x84\x01+"
    if len(raw) < 128:
        length = bytes([len(raw)])
    else:
        length = b"\x81" + len(raw).to_bytes(2, "little")
    return prefix + length + raw


def build(path: Path, n_messages: int = 50_000, blob_fraction: float = 0.7) -> Path:
    """Create a synthetic chat.db at `path` with `n_messages` rows."""
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT, service TEXT);
        CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, chat_identifier TEXT,
                           display_name TEXT, service_name TEXT);
        CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT,
                              attributedBody BLOB, is_from_me INTEGER,
                              handle_id INTEGER, date INTEGER, service TEXT,
                              cache_has_attachments INTEGER);
        CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
        CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
        CREATE TABLE attachment (ROWID INTEGER PRIMARY KEY, filename TEXT,
                                 mime_type TEXT, transfer_name TEXT,
                                 total_bytes INTEGER);
        CREATE TABLE message_attachment_join (message_id INTEGER,
                                              attachment_id INTEGER);
        """
    )
    handles = [(i, f"+1415555{i:04d}", "iMessage") for i in range(1, 21)]
    conn.executemany("INSERT INTO handle VALUES (?,?,?)", handles)
    chats = [(i, f"chat{i}", f"Chat {i}", "iMessage") for i in range(1, 11)]
    conn.executemany(
        "INSERT INTO chat VALUES (?,?,?,?)", chats
    )

    base_date = 700_000_000 * 1_000_000_000  # arbitrary apple-epoch nanoseconds
    blob_cut = int(n_messages * blob_fraction)
    msgs = []
    joins = []
    for i in range(1, n_messages + 1):
        body = f"benchmark message number {i} lorem ipsum dolor sit amet"
        handle_id = (i % 20) + 1
        is_me = i % 3 == 0
        if i <= blob_cut:  # stored as attributedBody, text NULL
            row = (i, None, _attributed_body(body), int(is_me), handle_id,
                   base_date + i * 1_000_000_000, "iMessage", 0)
        else:  # plain text column
            row = (i, body, None, int(is_me), handle_id,
                   base_date + i * 1_000_000_000, "iMessage", 0)
        msgs.append(row)
        joins.append(((i % 10) + 1, i))
    conn.executemany("INSERT INTO message VALUES (?,?,?,?,?,?,?,?)", msgs)
    conn.executemany("INSERT INTO chat_message_join VALUES (?,?)", joins)

    # Every 10th message carries an attachment backed by a real file on disk, so
    # tests can exercise copying. The last one is intentionally left dangling
    # (row present, file absent) to cover the missing-source path.
    media_dir = path.parent / "Attachments"
    media_dir.mkdir(exist_ok=True)
    attach_msgs = [i for i in range(1, n_messages + 1) if i % 10 == 0]
    attachments, ajoins = [], []
    for n, msg_id in enumerate(attach_msgs, start=1):
        kind = ("jpeg", "image/jpeg") if n % 2 else ("caf", "audio/x-caf")
        name = f"media_{n}.{kind[0]}"
        f = media_dir / name
        if n != len(attach_msgs):  # leave the final one dangling
            f.write_bytes(b"\xff\xd8\xff" + name.encode())
        attachments.append((n, str(f), kind[1], name, f.stat().st_size if f.exists() else 0))
        ajoins.append((msg_id, n))
        conn.execute(
            "UPDATE message SET cache_has_attachments = 1 WHERE ROWID = ?", (msg_id,)
        )
    conn.executemany("INSERT INTO attachment VALUES (?,?,?,?,?)", attachments)
    conn.executemany("INSERT INTO message_attachment_join VALUES (?,?)", ajoins)
    conn.commit()
    conn.close()
    return path


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50_000
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/tmp/imsg_bench.db")
    build(out, n)
    print(f"wrote {out} ({n} messages)")
