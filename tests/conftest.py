"""Shared fixtures: a small synthetic chat.db built with stdlib sqlite3.

Never reads a real Messages database (or a real AddressBook).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bench.make_db import build  # noqa: E402


@pytest.fixture()
def synthetic_db(tmp_path: Path) -> Path:
    return build(tmp_path / "chat.db", n_messages=30, blob_fraction=0.5)


@pytest.fixture()
def addressbook_db(tmp_path: Path) -> Path:
    """A synthetic AddressBook-v22.abcddb with a handful of contacts, covering
    an exact/partial-name match, a name collision (ambiguous), and a
    phone-only vs email-only contact."""
    db = tmp_path / "AddressBook-v22.abcddb"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE ZABCDRECORD (Z_PK INTEGER PRIMARY KEY, ZFIRSTNAME TEXT, ZLASTNAME TEXT);
        CREATE TABLE ZABCDPHONENUMBER (Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER, ZFULLNUMBER TEXT);
        CREATE TABLE ZABCDEMAILADDRESS (Z_PK INTEGER PRIMARY KEY, ZOWNER INTEGER, ZADDRESS TEXT);
        """
    )
    conn.executemany(
        "INSERT INTO ZABCDRECORD (Z_PK, ZFIRSTNAME, ZLASTNAME) VALUES (?,?,?)",
        [
            (1, "Joseph", "Heupler"),
            (2, "Jose", "Ramirez"),
            (3, "Jose", "Alvarez"),
            (4, "NoHandle", "Person"),
        ],
    )
    conn.executemany(
        "INSERT INTO ZABCDPHONENUMBER (ZOWNER, ZFULLNUMBER) VALUES (?,?)",
        [
            (1, "(626) 234-4927"),
            (2, "+1 415-555-0100"),
        ],
    )
    conn.executemany(
        "INSERT INTO ZABCDEMAILADDRESS (ZOWNER, ZADDRESS) VALUES (?,?)",
        [(3, "jose.alvarez@example.com")],
    )
    conn.commit()
    conn.close()
    return db
