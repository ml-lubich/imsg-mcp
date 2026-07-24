"""Tests for imessage_mcp.ui gradient renderer and helpers."""
from __future__ import annotations

import pytest
from rich.console import Console
from rich.panel import Panel
from rich.status import Status
from rich.table import Table
from rich.text import Text

from imessage_mcp import ui


def test_gradient_text_empty_string():
    result = ui.gradient_text("", "#ff0000", "#0000ff")
    assert result.plain == ""
    assert len(result.spans) == 0


def test_gradient_text_single_char():
    result = ui.gradient_text("x", "#ff0000", "#0000ff")
    assert result.plain == "x"
    assert len(result.spans) == 1
    assert "#ff0000" in str(result.spans[0].style)


def test_badge_sent_state():
    result = ui.badge("sent")
    assert "sent" in result.plain
    assert "✓" in result.plain


def test_badge_unknown_state_raises():
    with pytest.raises(ValueError, match="unknown badge state"):
        ui.badge("bogus")


def test_spinner_returns_status():
    assert isinstance(ui.spinner("working"), Status)


def test_banner_and_table_render():
    table = ui.styled_table("Chats", ["id", "name"])
    table.add_row("1", "Alice")
    console = Console(record=True, width=80)
    console.print(ui.banner())
    console.print(table)
    output = console.export_text()
    assert "Alice" in output


def test_error_panel():
    panel = ui.error_panel("something failed")
    assert isinstance(panel, Panel)
    console = Console(record=True, width=80)
    console.print(panel)
    assert "something failed" in console.export_text()
