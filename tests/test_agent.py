"""Agent schema/guide unit tests and CLI wiring."""
from __future__ import annotations

import json

from typer.testing import CliRunner

from imessage_mcp import agent, main

runner = CliRunner()


def test_build_schema_has_expected_keys():
    schema = agent.build_schema()
    assert schema["tool"] == "imsg"
    assert schema["mcp"] == "imsg-mcp"
    assert schema["version"] == "0.1.2"
    names = {c["name"] for c in schema["commands"]}
    assert {"doctor", "send", "agent schema", "agent guide"} <= names


def test_build_guide_mentions_cli_and_mcp():
    guide = agent.build_guide()
    assert "imsg agent schema" in guide
    assert "imsg-mcp" in guide or "MCP" in guide


def test_agent_schema_cli():
    result = runner.invoke(main.app, ["agent", "schema"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["tool"] == "imsg"
    assert payload["mcp"] == "imsg-mcp"


def test_agent_guide_cli():
    result = runner.invoke(main.app, ["agent", "guide"])
    assert result.exit_code == 0
    assert "imsg agent guide" in result.stdout
