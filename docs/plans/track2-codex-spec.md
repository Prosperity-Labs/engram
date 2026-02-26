# Agent Spec: Codex — Loop Controller + MCP Auto-Install

> **Branch:** `feat/nl-search-mcp`
> **Agent:** Codex
> **Scope:** `engram/cli.py` (modify) + `engram/install_mcp.py` (new) + `tests/test_install_mcp.py` (new)

---

## Context

Engram already has:
- `engram install` — indexes all sessions into the knowledge base
- `engram hooks install` — writes Claude Code hook config to `~/.claude/settings.json`
- `.mcp.json` in the repo root — but this only works when Claude Code opens the engram repo itself

The gap: when a user installs engram (`pip install engram` or `uvx engram`), there's no automatic MCP wiring. They have to manually create `.mcp.json` in every project. We need `engram install` to set up the MCP server config alongside the hook, so it's zero-setup.

Cursor is separately building the NL query rewriter for the MCP server. Your job is the install/wiring side.

---

## Task 1: MCP Config Installer Module

**New file:** `engram/install_mcp.py`

```python
"""Auto-wire Engram MCP server into Claude Code projects.

Writes MCP server config so Claude Code discovers engram automatically.
Supports both global (~/.claude/settings.json) and project-level (.mcp.json).
"""

from __future__ import annotations

import json
from pathlib import Path

# The MCP server config entry
ENGRAM_MCP_CONFIG = {
    "engram": {
        "command": "engram",
        "args": ["mcp"],
    }
}


def install_mcp_global() -> dict:
    """Add engram MCP server to Claude Code global settings.

    Writes to ~/.claude/settings.json under the "mcpServers" key.
    Idempotent — safe to run multiple times.

    Returns:
        {"installed": bool, "path": str, "already_existed": bool}
    """
    settings_path = Path.home() / ".claude" / "settings.json"

    # Read existing settings or start fresh
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, OSError):
            settings = {}
    else:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings = {}

    # Check if already configured
    mcp_servers = settings.get("mcpServers", {})
    if "engram" in mcp_servers:
        return {
            "installed": True,
            "path": str(settings_path),
            "already_existed": True,
        }

    # Add engram MCP config
    mcp_servers.update(ENGRAM_MCP_CONFIG)
    settings["mcpServers"] = mcp_servers

    # Write back
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")

    return {
        "installed": True,
        "path": str(settings_path),
        "already_existed": False,
    }


def install_mcp_project(project_dir: Path | str | None = None) -> dict:
    """Add engram MCP server to a project's .mcp.json.

    Args:
        project_dir: Project root directory. Uses cwd if not provided.

    Returns:
        {"installed": bool, "path": str, "already_existed": bool}
    """
    project_dir = Path(project_dir) if project_dir else Path.cwd()
    mcp_path = project_dir / ".mcp.json"

    # Read existing config or start fresh
    if mcp_path.exists():
        try:
            config = json.loads(mcp_path.read_text())
        except (json.JSONDecodeError, OSError):
            config = {}
    else:
        config = {}

    # Check if already configured
    mcp_servers = config.get("mcpServers", {})
    if "engram" in mcp_servers:
        return {
            "installed": True,
            "path": str(mcp_path),
            "already_existed": True,
        }

    # Add engram MCP config
    mcp_servers.update(ENGRAM_MCP_CONFIG)
    config["mcpServers"] = mcp_servers

    # Write back
    mcp_path.write_text(json.dumps(config, indent=2) + "\n")

    return {
        "installed": True,
        "path": str(mcp_path),
        "already_existed": False,
    }
```

---

## Task 2: Wire into `engram install`

**Modify:** `engram/cli.py`

Add MCP installation to the existing `cmd_install` function. At the end of `cmd_install`, after indexing sessions, add:

```python
    # Auto-wire MCP server
    from .install_mcp import install_mcp_global
    mcp_result = install_mcp_global()
    if mcp_result["already_existed"]:
        print(f"  MCP server: already configured in {mcp_result['path']}")
    else:
        print(f"  MCP server: registered in {mcp_result['path']}")
```

Also add a dedicated `engram mcp install` subcommand for standalone MCP setup:

Add to `main()` after the existing `mcp` subparser:

```python
# mcp install (standalone MCP wiring)
p_mcp_install = subparsers.add_parser("mcp-install", help="Register engram MCP server with Claude Code")
p_mcp_install.add_argument("--global", dest="global_install", action="store_true", default=True,
                            help="Install to ~/.claude/settings.json (default)")
p_mcp_install.add_argument("--project", "-p", dest="project_dir",
                            help="Install to project .mcp.json instead")
p_mcp_install.set_defaults(func=cmd_mcp_install)
```

Add the command function:

```python
def cmd_mcp_install(args: argparse.Namespace) -> None:
    """Register engram MCP server with Claude Code."""
    from .install_mcp import install_mcp_global, install_mcp_project

    if args.project_dir:
        result = install_mcp_project(args.project_dir)
    else:
        result = install_mcp_global()

    if result["already_existed"]:
        print(f"Engram MCP already configured in {result['path']}")
    else:
        print(f"Engram MCP server registered in {result['path']}")
        print("Restart Claude Code to activate.")
```

---

## Task 3: Tests

**New file:** `tests/test_install_mcp.py`

```python
"""Tests for MCP auto-install."""

import json
import pytest
from pathlib import Path
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
```

---

## Verification

When done:

1. Run existing tests: `pytest tests/ -v` — all must pass (no regressions)
2. Run new tests: `pytest tests/test_install_mcp.py -v`
3. Test CLI:
   ```bash
   engram mcp-install --help         # shows usage
   engram mcp-install                # installs globally
   engram mcp-install --project .    # installs to current project
   ```
4. Test that `engram install` now prints MCP status at the end
5. `git add engram/install_mcp.py engram/cli.py tests/test_install_mcp.py`
6. `git commit -m 'feat: auto-wire MCP server on engram install (Track 2)'`
7. Do NOT `git push`
