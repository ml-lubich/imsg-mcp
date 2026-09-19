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
import re
import sqlite3
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Apple's Core Data epoch: 2001-01-01 UTC, in unix seconds.
_APPLE_EPOCH = 978307200

DEFAULT_DB = Path.home() / "Library" / "Messages" / "chat.db"

# Per-account AddressBook stores live under Sources/<uuid>/AddressBook-v22.abcddb.
DEFAULT_ADDRESSBOOK_SOURCES = (
    Path.home() / "Library" / "Application Support" / "AddressBook" / "Sources"
)

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
    name: str | None = None  # set when resolved from AddressBook by name

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
    addressbook_paths: list[Path] | None = None,
) -> list[Contact]:
    """Distinct handles (phone numbers / emails) seen in the message store,
    plus any macOS AddressBook contacts whose display name matches `query`.

    `query` matches case-insensitively against a contact's display name (read
    straight from the local AddressBook SQLite store, no osascript) OR a
    handle substring, e.g. a partial phone number or email domain. Name
    matches are listed first, one row per handle, with `name` set; handle-only
    matches keep the prior behavior (`name` is None).
    """
    needle = (query or "").strip() or None

    named: list[Contact] = []
    if needle:
        for name, handles in find_contacts_by_name(needle, db_paths=addressbook_paths):
            for h in handles:
                named.append(Contact(handle=h, service=None, name=name))

    if _RUST is not None:
        rows = _via_rust(
            lambda: _RUST.list_contacts(str(path or db_path()), limit, needle)
        )
        handle_contacts = [Contact(*r) for r in rows]
    else:
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
            handle_contacts = [Contact(r[0], r[1]) for r in _rows(cur)]
        finally:
            conn.close()

    seen = {c.handle for c in named}
    merged = named + [c for c in handle_contacts if c.handle not in seen]
    return merged[:limit]


def _addressbook_db_paths(base: Path | None = None) -> list[Path]:
    """Every per-account AddressBook-v22.abcddb under Sources/*."""
    root = base or DEFAULT_ADDRESSBOOK_SOURCES
    if not root.exists():
        return []
    return sorted(root.glob("*/AddressBook-v22.abcddb"))


def _normalize_phone(raw: str) -> str:
    """Best-effort normalization to the `+1XXXXXXXXXX`-style form chat.db uses
    for US handles, so an AddressBook number matches a `handle.id`.

    ponytail: US/NANP heuristic (10 digits -> +1…, 11 starting with 1 -> +…);
    a number that already has a country code (e.g. "+44 ...") passes through
    with only punctuation stripped. Upgrade to a real E.164 library
    (phonenumbers) if non-US numbers start mismatching chat.db handles.
    """
    if raw.strip().startswith("+"):
        return "+" + re.sub(r"\D", "", raw)
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return raw.strip()
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return f"+{digits}"


def find_contacts_by_name(
    name: str,
    db_paths: list[Path] | None = None,
) -> list[tuple[str, list[str]]]:
    """Contacts whose display name contains `name` (case-insensitive substring),
    read read-only straight from the macOS AddressBook SQLite store(s) — no
    osascript against Contacts.app.

    Returns a sorted list of `(full_name, handles)` pairs. `handles` are phone
    numbers normalized to chat.db's `+1XXXXXXXXXX` form plus any emails,
    deduplicated; a contact with no phone/email is omitted (it can't be a send
    target). `db_paths` overrides discovery (used by tests with a fixture DB).
    """
    needle = name.strip().lower()
    if not needle:
        return []
    paths = _addressbook_db_paths() if db_paths is None else db_paths
    found: dict[str, list[str]] = {}
    for db in paths:
        if not Path(db).exists():
            continue
        try:
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        except sqlite3.OperationalError:
            continue
        try:
            cur = conn.execute(
                """
                SELECT Z_PK, TRIM(COALESCE(ZFIRSTNAME,'') || ' ' || COALESCE(ZLASTNAME,''))
                FROM ZABCDRECORD
                WHERE LOWER(COALESCE(ZFIRSTNAME,'') || ' ' || COALESCE(ZLASTNAME,'')) LIKE ?
                """,
                (f"%{needle}%",),
            )
            for pk, full_name in cur.fetchall():
                if not full_name:
                    continue
                handles = found.setdefault(full_name, [])
                for (num,) in conn.execute(
                    "SELECT ZFULLNUMBER FROM ZABCDPHONENUMBER WHERE ZOWNER = ?", (pk,)
                ):
                    if num:
                        norm = _normalize_phone(num)
                        if norm not in handles:
                            handles.append(norm)
                for (addr,) in conn.execute(
                    "SELECT ZADDRESS FROM ZABCDEMAILADDRESS WHERE ZOWNER = ?", (pk,)
                ):
                    if addr and addr not in handles:
                        handles.append(addr)
        finally:
            conn.close()
    return sorted((n, h) for n, h in found.items() if h)


def _pick_imessage_handle(handles: list[str], path: Path | None = None) -> str:
    """Of a contact's handles, prefer one chat.db already knows as iMessage.

    Falls back to the first handle when there's only one, chat.db isn't
    readable, or none of them are known iMessage handles yet.
    """
    if len(handles) == 1:
        return handles[0]
    try:
        conn = _connect(path)
    except AccessError:
        return handles[0]
    try:
        placeholders = ",".join("?" * len(handles))
        cur = conn.execute(
            f"SELECT id FROM handle WHERE service = 'iMessage' AND id IN ({placeholders})",
            handles,
        )
        known = {r[0] for r in cur.fetchall()}
        for h in handles:
            if h in known:
                return h
    finally:
        conn.close()
    return handles[0]


_HANDLE_RE = re.compile(r"^[\d+()\-.\s]+$")


def resolve_recipient(
    recipient: str,
    path: Path | None = None,
    addressbook_paths: list[Path] | None = None,
) -> str:
    """Resolve `recipient` to a single handle for `send_message`.

    A phone number or email passes through unchanged. A display name is
    resolved via the local AddressBook to exactly one contact's
    iMessage-capable handle. Raises ValueError — never sends — when the name
    matches zero or more than one contact, listing the candidates found.
    """
    if "@" in recipient or _HANDLE_RE.match(recipient.strip()):
        return recipient
    matches = find_contacts_by_name(recipient, db_paths=addressbook_paths)
    if not matches:
        raise ValueError(f"no contact matching {recipient!r}")
    if len(matches) > 1:
        candidates = "; ".join(f"{n} ({', '.join(h)})" for n, h in matches)
        raise ValueError(f"ambiguous name {recipient!r}, matches: {candidates}")
    name, handles = matches[0]
    return _pick_imessage_handle(handles, path=path)


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


def send_message(
    recipient: str,
    text: str,
    path: Path | None = None,
    addressbook_paths: list[Path] | None = None,
) -> None:
    """Send an iMessage/SMS to a handle (phone number or email) via Messages.app.

    `recipient` may also be a contact name (e.g. "Joseph Heupler"); it is
    resolved via `resolve_recipient` to exactly one handle before anything is
    sent — an ambiguous or unmatched name raises ValueError and never sends.

    Tries the iMessage service first; Messages falls back to SMS for handles
    that aren't on iMessage when the account allows it.
    """
    if not recipient or not text:
        raise ValueError("recipient and text are required")
    recipient = resolve_recipient(recipient, path=path, addressbook_paths=addressbook_paths)
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
