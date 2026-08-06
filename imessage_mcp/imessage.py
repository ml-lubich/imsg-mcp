"""Core iMessage access: read the local chat.db (read-only) and send via osascript.

No bridge or daemon is needed. Unlike WhatsApp (remote data behind a Go
bridge), iMessage data already lives locally in ~/Library/Messages/chat.db and
Messages.app can be driven with AppleScript. The CLI and the MCP server both
call the functions here directly.

Requirements at runtime:
  - Full Disk Access for the process reading chat.db (System Settings ->
    Privacy & Security -> Full Disk Access -> add your terminal / the app).
  - Automation permission for Messages.app (granted on first send).
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Apple's Core Data epoch: 2001-01-01 UTC, in unix seconds.
_APPLE_EPOCH = 978307200

DEFAULT_DB = Path.home() / "Library" / "Messages" / "chat.db"

try:  # Rust-accelerated core; falls back to pure Python when absent.
    import imsgcore as _RUST
except ImportError:  # pragma: no cover - depends on build
    _RUST = None


class AccessError(RuntimeError):
    """chat.db exists but cannot be opened (missing Full Disk Access)."""


def db_path() -> Path:
    """The chat.db path, overridable via IMESSAGE_DB (handy for tests)."""
    return Path(os.environ.get("IMESSAGE_DB", str(DEFAULT_DB)))


def _connect(path: Path | None = None):
    import sqlite3

    p = path or db_path()
    if not p.exists():
        raise AccessError(f"chat.db not found at {p}")
    try:
        return sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:  # pragma: no cover - env specific
        raise AccessError(
            f"cannot open {p}: {exc}. Grant Full Disk Access to this terminal "
            "in System Settings -> Privacy & Security -> Full Disk Access."
        ) from exc


def _via_rust(thunk):
    """Run a Rust core call, translating its RuntimeError (e.g. an unopenable
    chat.db from missing Full Disk Access) into AccessError so the CLI/MCP
    handle it the same way as the pure-Python path."""
    try:
        return thunk()
    except RuntimeError as exc:
        raise AccessError(
            f"cannot open {db_path()}: {exc}. Grant Full Disk Access to this "
            "terminal in System Settings -> Privacy & Security -> Full Disk "
            "Access, then fully quit and reopen it."
        ) from exc


def _apple_time_to_iso(raw: int | None) -> str | None:
    """Convert a chat.db `date` value to an ISO-8601 UTC string.

    Modern macOS stores nanoseconds since the Apple epoch; older stores
    seconds. Disambiguate by magnitude (ns values are ~1e18).
    """
    if not raw:
        return None
    seconds = raw / 1_000_000_000 if raw > 1_000_000_000_000 else raw
    ts = seconds + _APPLE_EPOCH
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _decode_attributed_body(blob: bytes | None) -> str | None:
    """Best-effort text extraction from a message's attributedBody blob.

    Newer messages leave `text` NULL and stash the body in a typedstream
    archive. This scans for the NSString payload and reads its length-prefixed
    UTF-8 content — the widely-used heuristic.

    ponytail: byte-scan heuristic, not a full typedstream parser. Handles the
    common single-run case; upgrade to `pip install pytypedstream` if rich
    multi-run attributed strings start losing text.
    """
    if not blob or b"NSString" not in blob:
        return None
    data = blob.split(b"NSString", 1)[1]
    # Skip the class-version bytes that precede the length marker.
    data = data[5:]
    if not data:
        return None
    marker = data[0]
    if marker == 0x81:  # 2-byte little-endian length
        if len(data) < 3:
            return None
        length = int.from_bytes(data[1:3], "little")
        start = 3
    else:  # single-byte length
        length = marker
        start = 1
    text = data[start : start + length].decode("utf-8", errors="replace")
    return text or None


@dataclass
class Chat:
    chat_id: int
    identifier: str
    name: str | None
    service: str | None

    def dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Message:
    text: str | None
    sender: str  # "me" or a handle id (phone/email)
    is_from_me: bool
    date: str | None
    service: str | None
    has_attachment: bool

    def dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Contact:
    handle: str  # phone number or email
    service: str | None

    def dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Attachment:
    """A media/file attachment, with `filename` resolved to an absolute path."""

    message_id: int
    chat_id: int | None
    filename: str
    mime_type: str
    transfer_name: str  # original name as sent, used when saving
    total_bytes: int
    date: str | None
    is_from_me: bool
    sender: str
    exists: bool  # False when the backing file was pruned or is iCloud-only

    def dict(self) -> dict[str, Any]:
        return asdict(self)


def _rows(cur) -> Iterable[tuple]:
    while True:
        row = cur.fetchone()
        if row is None:
            return
        yield row


def list_chats(limit: int = 20, path: Path | None = None) -> list[Chat]:
    """Recent conversations, most-recently-active first."""
    if _RUST is not None:
        rows = _via_rust(lambda: _RUST.list_chats(str(path or db_path()), limit))
        return [Chat(*r) for r in rows]
    conn = _connect(path)
    try:
        cur = conn.execute(
            """
            SELECT c.ROWID, c.chat_identifier, c.display_name, c.service_name,
                   MAX(m.date) AS last
            FROM chat c
            JOIN chat_message_join cmj ON cmj.chat_id = c.ROWID
            JOIN message m ON m.ROWID = cmj.message_id
            GROUP BY c.ROWID
            ORDER BY last DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [Chat(r[0], r[1], r[2], r[3]) for r in _rows(cur)]
    finally:
        conn.close()


def list_contacts(
    limit: int = 100,
    query: str | None = None,
    path: Path | None = None,
) -> list[Contact]:
    """Distinct handles (phone numbers / emails) seen in the message store.

    Optional `query` substring-filters handles (case-insensitive), e.g. a
    partial phone number or email domain.
    """
    needle = (query or "").strip() or None
    if _RUST is not None:
        rows = _via_rust(
            lambda: _RUST.list_contacts(str(path or db_path()), limit, needle)
        )
        return [Contact(*r) for r in rows]
    conn = _connect(path)
    try:
        if needle:
            cur = conn.execute(
                "SELECT DISTINCT id, service FROM handle "
                "WHERE id LIKE ? COLLATE NOCASE ORDER BY id LIMIT ?",
                (f"%{needle}%", limit),
            )
        else:
            cur = conn.execute(
                "SELECT DISTINCT id, service FROM handle ORDER BY id LIMIT ?",
                (limit,),
            )
        return [Contact(r[0], r[1]) for r in _rows(cur)]
    finally:
        conn.close()


def _message_from_rust(t: tuple) -> Message:
    """Wrap a tuple from imsgcore into a Message.

    Rust returns (text|None, is_from_me, sender, date_raw, service, has_attach)
    with text already resolved (attributedBody decoded in Rust).
    """
    text, is_from_me, sender, date_raw, service, has_attach = t
    return Message(
        text=text,
        sender=sender,
        is_from_me=bool(is_from_me),
        date=_apple_time_to_iso(date_raw),
        service=service,
        has_attachment=bool(has_attach),
    )


def _message_from_row(row: tuple) -> Message:
    text, body, is_from_me, handle, date, service, has_attach = row
    resolved = text or _decode_attributed_body(body)
    return Message(
        text=resolved,
        sender="me" if is_from_me else (handle or "unknown"),
        is_from_me=bool(is_from_me),
        date=_apple_time_to_iso(date),
        service=service,
        has_attachment=bool(has_attach),
    )


_MESSAGE_COLS = (
    "m.text, m.attributedBody, m.is_from_me, h.id, m.date, m.service, "
    "m.cache_has_attachments"
)


def read_messages(
    contact: str | None = None,
    chat_id: int | None = None,
    limit: int = 20,
    path: Path | None = None,
) -> list[Message]:
    """Most recent messages, optionally filtered by contact handle or chat_id.

    Returned oldest-first (chronological) for readable transcripts.
    """
    if _RUST is not None:
        rows = _via_rust(lambda: _RUST.read_messages(str(path or db_path()), contact, chat_id, limit))
        return list(reversed([_message_from_rust(r) for r in rows]))
    conn = _connect(path)
    try:
        where = []
        params: list[Any] = []
        if chat_id is not None:
            where.append(
                "m.ROWID IN (SELECT message_id FROM chat_message_join WHERE chat_id = ?)"
            )
            params.append(chat_id)
        if contact:
            where.append("h.id = ?")
            params.append(contact)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        params.append(limit)
        cur = conn.execute(
            f"""
            SELECT {_MESSAGE_COLS}
            FROM message m
            LEFT JOIN handle h ON h.ROWID = m.handle_id
            {clause}
            ORDER BY m.date DESC
            LIMIT ?
            """,
            params,
        )
        msgs = [_message_from_row(r) for r in _rows(cur)]
        return list(reversed(msgs))
    finally:
        conn.close()


def search_messages(query: str, limit: int = 20, path: Path | None = None) -> list[Message]:
    """Full-text-ish LIKE search over message bodies, newest first."""
    if _RUST is not None:
        rows = _via_rust(lambda: _RUST.search_messages(str(path or db_path()), query, limit))
        return [_message_from_rust(r) for r in rows]
    conn = _connect(path)
    try:
        cur = conn.execute(
            f"""
            SELECT {_MESSAGE_COLS}
            FROM message m
            LEFT JOIN handle h ON h.ROWID = m.handle_id
            WHERE m.text LIKE ?
            ORDER BY m.date DESC
            LIMIT ?
            """,
            (f"%{query}%", limit),
        )
        return [_message_from_row(r) for r in _rows(cur)]
    finally:
        conn.close()


def search_all(query: str, limit: int = 100, path: Path | None = None) -> list[Message]:
    """Search the FULL history, including messages stored as attributedBody
    blobs that a plain `text LIKE` query silently misses.

    Rust decodes and matches every message in parallel across cores; the
    pure-Python fallback below does the same single-threaded (and is the honest
    baseline the benchmark compares against).
    """
    if _RUST is not None:
        rows = _via_rust(lambda: _RUST.search_all(str(path or db_path()), query, limit))
        return [_message_from_rust(r) for r in rows]

    needle = query.lower()
    conn = _connect(path)
    try:
        cur = conn.execute(
            f"SELECT {_MESSAGE_COLS} FROM message m "
            "LEFT JOIN handle h ON h.ROWID = m.handle_id ORDER BY m.date DESC"
        )
        out: list[Message] = []
        for row in _rows(cur):
            msg = _message_from_row(row)
            if msg.text and needle in msg.text.lower():
                out.append(msg)
                if len(out) >= limit:
                    break
        return out
    finally:
        conn.close()


def _expand_attachment_path(filename: str | None) -> Path | None:
    """Resolve a chat.db `attachment.filename` to an absolute path.

    Messages stores these as `~/Library/Messages/Attachments/...`, so the tilde
    has to be expanded before the file can be read.
    """
    if not filename:
        return None
    return Path(filename).expanduser()


def list_attachments(
    contact: str | None = None,
    chat_id: int | None = None,
    limit: int = 20,
    kind: str | None = None,
    path: Path | None = None,
) -> list[Attachment]:
    """Attachments (images, audio, video, files) newest first.

    `kind` filters on the mime-type prefix, e.g. "image", "audio", "video".
    Attachments live on disk next to chat.db, so `download_attachments` is just
    a copy — nothing is fetched over the network.
    """
    where, params = [], []
    if contact:
        where.append("h.id = ?")
        params.append(contact)
    if chat_id is not None:
        where.append("cmj.chat_id = ?")
        params.append(chat_id)
    if kind:
        where.append("a.mime_type LIKE ?")
        params.append(f"{kind}%")
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    params.append(limit)

    conn = _connect(path)
    try:
        cur = conn.execute(
            f"""
            SELECT m.ROWID, cmj.chat_id, a.filename, a.mime_type, a.transfer_name,
                   a.total_bytes, m.date, m.is_from_me, h.id
            FROM attachment a
            JOIN message_attachment_join maj ON maj.attachment_id = a.ROWID
            JOIN message m ON m.ROWID = maj.message_id
            LEFT JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            LEFT JOIN handle h ON h.ROWID = m.handle_id
            {clause}
            ORDER BY m.date DESC
            LIMIT ?
            """,
            params,
        )
        out: list[Attachment] = []
        for row in _rows(cur):
            (msg_id, cid, fname, mime, tname, nbytes, date, is_me, handle) = row
            resolved = _expand_attachment_path(fname)
            out.append(
                Attachment(
                    message_id=msg_id,
                    chat_id=cid,
                    filename=str(resolved) if resolved else "",
                    mime_type=mime or "",
                    transfer_name=tname or (resolved.name if resolved else ""),
                    total_bytes=nbytes or 0,
                    date=_apple_time_to_iso(date),
                    is_from_me=bool(is_me),
                    sender="me" if is_me else (handle or "unknown"),
                    exists=bool(resolved and resolved.is_file()),
                )
            )
        return out
    finally:
        conn.close()


def _unique_dest(dest_dir: Path, name: str) -> Path:
    """A non-colliding path in `dest_dir`, suffixing -1, -2, ... as needed."""
    candidate = dest_dir / name
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    n = 1
    while (dest_dir / f"{stem}-{n}{suffix}").exists():
        n += 1
    return dest_dir / f"{stem}-{n}{suffix}"


def download_attachments(
    dest_dir: Path | str,
    contact: str | None = None,
    chat_id: int | None = None,
    limit: int = 20,
    kind: str | None = None,
    path: Path | None = None,
) -> list[Path]:
    """Copy matching attachments into `dest_dir`; return the written paths.

    Rows whose backing file is missing (Messages prunes them, or iCloud has not
    downloaded them yet) are skipped rather than raising, so one gap does not
    abort the batch.
    """
    import shutil

    dest = Path(dest_dir).expanduser()
    if dest.exists() and not dest.is_dir():
        raise ValueError(f"destination is not a directory: {dest}")
    dest.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for att in list_attachments(
        contact=contact, chat_id=chat_id, limit=limit, kind=kind, path=path
    ):
        if not att.exists:
            continue
        target = _unique_dest(dest, att.transfer_name or Path(att.filename).name)
        shutil.copy2(att.filename, target)
        written.append(target)
    return written


def _osascript(script: str) -> None:
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "osascript failed")


def send_message(recipient: str, text: str) -> None:
    """Send an iMessage/SMS to a handle (phone number or email) via Messages.app.

    Tries the iMessage service first; Messages falls back to SMS for handles
    that aren't on iMessage when the account allows it.
    """
    if not recipient or not text:
        raise ValueError("recipient and text are required")
    safe_text = text.replace("\\", "\\\\").replace('"', '\\"')
    safe_recip = recipient.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
    tell application "Messages"
        set targetService to 1st account whose service type = iMessage
        set targetBuddy to participant "{safe_recip}" of targetService
        send "{safe_text}" to targetBuddy
    end tell
    '''
    _osascript(script)
