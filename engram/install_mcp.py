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
