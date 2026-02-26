"""Tests for MCP auto-install."""

import json
from pathlib import Path

import pytest

from engram.install_mcp import install_mcp_global, install_mcp_project


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Override HOME to use tmp_path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    # Also patch Path.home() for consistency
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


class TestGlobalInstall:
    def test_creates_settings_if_missing(self, fake_home):
        result = install_mcp_global()
        assert result["installed"] is True
        assert result["already_existed"] is False

        settings = json.loads((fake_home / ".claude" / "settings.json").read_text())
        assert "engram" in settings["mcpServers"]
        assert settings["mcpServers"]["engram"]["command"] == "engram"

    def test_adds_to_existing_settings(self, fake_home):
        # Pre-existing settings with other config
        settings_dir = fake_home / ".claude"
        settings_dir.mkdir(parents=True)
        (settings_dir / "settings.json").write_text(json.dumps({
            "permissions": {"allow": ["some_tool"]},
            "mcpServers": {
                "other-server": {"command": "other"}
            }
        }))

        result = install_mcp_global()
        assert result["installed"] is True
        assert result["already_existed"] is False

        settings = json.loads((settings_dir / "settings.json").read_text())
        # Preserves existing config
        assert "other-server" in settings["mcpServers"]
        assert "engram" in settings["mcpServers"]
        assert "permissions" in settings

    def test_idempotent(self, fake_home):
        install_mcp_global()
        result = install_mcp_global()
        assert result["already_existed"] is True

    def test_handles_corrupt_json(self, fake_home):
        settings_dir = fake_home / ".claude"
        settings_dir.mkdir(parents=True)
        (settings_dir / "settings.json").write_text("not json{{{")

        result = install_mcp_global()
        assert result["installed"] is True
        # Should recover gracefully


class TestProjectInstall:
    def test_creates_mcp_json(self, tmp_path):
        result = install_mcp_project(tmp_path)
        assert result["installed"] is True

        config = json.loads((tmp_path / ".mcp.json").read_text())
        assert "engram" in config["mcpServers"]

    def test_preserves_existing_servers(self, tmp_path):
        (tmp_path / ".mcp.json").write_text(json.dumps({
            "mcpServers": {
                "noodlbox": {"command": "noodl", "args": ["mcp"]}
            }
        }))

        result = install_mcp_project(tmp_path)
        config = json.loads((tmp_path / ".mcp.json").read_text())
        assert "noodlbox" in config["mcpServers"]
        assert "engram" in config["mcpServers"]

    def test_idempotent(self, tmp_path):
        install_mcp_project(tmp_path)
        result = install_mcp_project(tmp_path)
        assert result["already_existed"] is True
