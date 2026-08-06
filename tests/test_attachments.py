"""Attachment listing and download (media/audio/files out of chat.db)."""
from __future__ import annotations

from pathlib import Path

import pytest

from imessage_mcp import imessage


def test_list_attachments_returns_rows(synthetic_db: Path) -> None:
    rows = imessage.list_attachments(limit=50, path=synthetic_db)
    assert rows, "synthetic db seeds attachments every 10th message"
    assert all(a.filename for a in rows)
    assert {a.mime_type for a in rows} == {"image/jpeg", "audio/x-caf"}


def test_list_attachments_respects_limit(synthetic_db: Path) -> None:
    assert len(imessage.list_attachments(limit=2, path=synthetic_db)) == 2


def test_list_attachments_filters_by_mime_prefix(synthetic_db: Path) -> None:
    rows = imessage.list_attachments(limit=50, kind="audio", path=synthetic_db)
    assert rows
    assert all(a.mime_type.startswith("audio") for a in rows)


def test_list_attachments_filters_by_chat(synthetic_db: Path) -> None:
    rows = imessage.list_attachments(limit=50, chat_id=1, path=synthetic_db)
    assert rows
    assert all(a.chat_id == 1 for a in rows)


def test_attachment_reports_existence(synthetic_db: Path) -> None:
    rows = imessage.list_attachments(limit=50, path=synthetic_db)
    assert any(a.exists for a in rows)
    assert any(not a.exists for a in rows), "final seeded attachment is dangling"


def test_expand_path_resolves_tilde() -> None:
    """Real chat.db stores '~/Library/...'; it must resolve to an absolute path."""
    p = imessage._expand_attachment_path("~/Library/Messages/Attachments/x/y.jpeg")
    assert p is not None
    assert p.is_absolute()
    assert "~" not in str(p)


def test_expand_path_handles_null() -> None:
    assert imessage._expand_attachment_path(None) is None


def test_download_attachments_copies_files(synthetic_db: Path, tmp_path: Path) -> None:
    dest = tmp_path / "out"
    saved = imessage.download_attachments(dest, limit=50, path=synthetic_db)
    assert saved
    for p in saved:
        assert p.exists()
        assert p.parent == dest
    # dangling row is skipped, not fatal
    assert len(saved) < len(imessage.list_attachments(limit=50, path=synthetic_db))


def test_download_creates_dest_and_dedupes_names(
    synthetic_db: Path, tmp_path: Path
) -> None:
    dest = tmp_path / "nested" / "out"
    first = imessage.download_attachments(dest, limit=50, path=synthetic_db)
    second = imessage.download_attachments(dest, limit=50, path=synthetic_db)
    assert dest.is_dir()
    # Re-downloading must not clobber the originals.
    assert set(first).isdisjoint(set(second))
    assert all(p.exists() for p in first + second)


def test_download_filters_by_kind(synthetic_db: Path, tmp_path: Path) -> None:
    saved = imessage.download_attachments(
        tmp_path / "img", limit=50, kind="image", path=synthetic_db
    )
    assert saved
    assert all(p.suffix == ".jpeg" for p in saved)


def test_download_rejects_file_as_dest(synthetic_db: Path, tmp_path: Path) -> None:
    clash = tmp_path / "not-a-dir"
    clash.write_text("x")
    with pytest.raises(ValueError):
        imessage.download_attachments(clash, limit=5, path=synthetic_db)


# --- CLI surface ---------------------------------------------------------

from typer.testing import CliRunner  # noqa: E402

from imessage_mcp import main  # noqa: E402

runner = CliRunner()


def _fake(**kw):
    base = dict(
        message_id=1, chat_id=2, filename="/tmp/a/photo.jpeg", mime_type="image/jpeg",
        transfer_name="photo.jpeg", total_bytes=2048, date="2026-08-04T10:48:49",
        is_from_me=False, sender="+14155551234", exists=True,
    )
    base.update(kw)
    return imessage.Attachment(**base)


def test_cli_attachments_renders(monkeypatch):
    monkeypatch.setattr(
        imessage, "list_attachments",
        lambda contact=None, chat_id=None, limit=20, kind=None: [_fake()],
    )
    r = runner.invoke(main.app, ["attachments"])
    assert r.exit_code == 0
    assert "photo.jpeg" in r.stdout
    assert "image/jpeg" in r.stdout


def test_cli_attachments_flags_missing_files(monkeypatch):
    monkeypatch.setattr(
        imessage, "list_attachments",
        lambda contact=None, chat_id=None, limit=20, kind=None: [_fake(exists=False)],
    )
    r = runner.invoke(main.app, ["attachments"])
    assert r.exit_code == 0 and "missing" in r.stdout


def test_cli_attachments_empty(monkeypatch):
    monkeypatch.setattr(
        imessage, "list_attachments",
        lambda contact=None, chat_id=None, limit=20, kind=None: [],
    )
    r = runner.invoke(main.app, ["attachments"])
    assert r.exit_code == 0 and "no attachments" in r.stdout


def test_cli_download_reports_saved(monkeypatch, tmp_path):
    monkeypatch.setattr(
        imessage, "download_attachments",
        lambda d, contact=None, chat_id=None, limit=20, kind=None: [Path(d) / "photo.jpeg"],
    )
    r = runner.invoke(main.app, ["download", "-o", str(tmp_path)])
    assert r.exit_code == 0 and "photo.jpeg" in r.stdout


def test_cli_download_requires_out():
    assert runner.invoke(main.app, ["download"]).exit_code != 0


def test_cli_download_surfaces_access_error(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise imessage.AccessError("no Full Disk Access")
    monkeypatch.setattr(imessage, "download_attachments", boom)
    r = runner.invoke(main.app, ["download", "-o", str(tmp_path)])
    assert r.exit_code == 1


def test_cli_download_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(
        imessage, "download_attachments",
        lambda d, contact=None, chat_id=None, limit=20, kind=None: [],
    )
    r = runner.invoke(main.app, ["download", "-o", str(tmp_path)])
    assert r.exit_code == 0 and "nothing downloaded" in r.stdout


def test_human_bytes():
    assert main._human_bytes(512) == "512B"
    assert main._human_bytes(2048) == "2.0KB"
    assert main._human_bytes(5 * 1024 * 1024) == "5.0MB"


def test_agent_schema_lists_new_commands():
    from imessage_mcp import agent
    names = {c["name"] for c in agent.build_schema()["commands"]}
    assert {"attachments", "download"} <= names
