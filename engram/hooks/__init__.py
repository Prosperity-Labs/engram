"""PreToolUse hook for Claude Code — just-in-time file context injection.

When the agent calls Read or Edit, this hook queries the artifacts table
for that file's history and injects a one-liner context comment.

~20 tokens per injection, zero cost when file has no history.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from engram.recall.session_db import SessionDB


def file_context(db: SessionDB, file_path: str) -> str | None:
    """Look up file history from artifacts table.

    Returns one-liner like:
    "endpoints.ts — 12 reads, 8 writes, 3 errors across 5 sessions.
     Last error: CORS (2026-02-19)"

    Returns None if file has no history.
    """
    sql_counts = """
    SELECT artifact_type, COUNT(*) as cnt,
           COUNT(DISTINCT a.session_id) as sessions
    FROM artifacts a
    JOIN sessions s ON s.session_id = a.session_id
    WHERE a.target = ?
    GROUP BY artifact_type
    """

    sql_last_error = """
    SELECT a.context, s.created_at
    FROM artifacts a
    JOIN sessions s ON s.session_id = a.session_id
    WHERE a.target = ? AND a.artifact_type = 'error'
    ORDER BY s.created_at DESC LIMIT 1
    """

    with db._connect() as conn:
        rows = conn.execute(sql_counts, (file_path,)).fetchall()
        if not rows:
            return None

        counts: dict[str, int] = {}
        total_sessions = 0
        for row in rows:
            counts[row["artifact_type"]] = row["cnt"]
            total_sessions = max(total_sessions, row["sessions"])

        reads = counts.get("file_read", 0)
        writes = counts.get("file_write", 0) + counts.get("file_create", 0)
        errors = counts.get("error", 0)

        if reads == 0 and writes == 0 and errors == 0:
            return None

        name = Path(file_path).name

        parts = []
        if reads:
            parts.append(f"{reads} reads")
        if writes:
            parts.append(f"{writes} writes")
        if errors:
            parts.append(f"{errors} errors")

        summary = f"{name} — {', '.join(parts)} across {total_sessions} sessions"

        if errors:
            error_row = conn.execute(sql_last_error, (file_path,)).fetchone()
            if error_row and error_row["context"]:
                error_text = error_row["context"][:80].strip()
                error_date = (error_row["created_at"] or "")[:10]
                summary += f'. Last error: "{error_text}" ({error_date})'

    return summary


def last_session_summary(db: SessionDB, project: str) -> str | None:
    """Summarize the most recent session for this project.

    Returns something like:
    "Last session (2h ago): edited auth/middleware.ts, ran npm test. 45 messages."

    Returns None if no prior sessions.
    """
    sql_session = """
    SELECT s.session_id, s.message_count, s.created_at, s.updated_at
    FROM sessions s
    WHERE s.project = ?
    ORDER BY s.updated_at DESC LIMIT 1
    """

    sql_top_files = """
    SELECT a.target, a.artifact_type
    FROM artifacts a
    WHERE a.session_id = ?
      AND a.artifact_type IN ('file_write', 'file_create', 'file_read')
    GROUP BY a.target, a.artifact_type
    ORDER BY COUNT(*) DESC
    LIMIT 5
    """

    sql_commands = """
    SELECT a.target
    FROM artifacts a
    WHERE a.session_id = ? AND a.artifact_type = 'command'
    GROUP BY a.target
    ORDER BY COUNT(*) DESC
    LIMIT 3
    """

    with db._connect() as conn:
        session_row = conn.execute(sql_session, (project,)).fetchone()
        if not session_row:
            return None

        session_id = session_row["session_id"]
        msg_count = session_row["message_count"] or 0
        updated = session_row["updated_at"] or ""

        file_rows = conn.execute(sql_top_files, (session_id,)).fetchall()
        cmd_rows = conn.execute(sql_commands, (session_id,)).fetchall()

    actions = []
    edited_files = []
    read_files = []
    for row in file_rows:
        name = Path(row["target"]).name
        if row["artifact_type"] in ("file_write", "file_create"):
            edited_files.append(name)
        else:
            read_files.append(name)

    if edited_files:
        actions.append(f"edited {', '.join(edited_files[:3])}")
    if read_files and not edited_files:
        actions.append(f"read {', '.join(read_files[:3])}")

    for row in cmd_rows:
        cmd = row["target"]
        short_cmd = cmd.split()[0] if cmd else ""
        if short_cmd and short_cmd not in ("cd", "ls"):
            actions.append(f"ran {short_cmd}")
            break

    action_str = ", ".join(actions) if actions else "explored codebase"
    date_str = updated[:10] if updated else "unknown"

    return f"Last session ({date_str}): {action_str}. {msg_count} messages."


def handle_pretool_hook(stdin_json: dict) -> dict | None:
    """Main hook handler. Called by the shell script via `engram hook-handle`.

    1. Parse tool_name and tool_input from stdin
    2. If Read or Edit: call file_context() for the file_path
    3. If context found: return hookSpecificOutput with additionalContext
    4. If no context: return None (exit 0, no output)
    """
    tool_name = stdin_json.get("tool_name", "")
    tool_input = stdin_json.get("tool_input", {})

    if tool_name not in ("Read", "Edit", "Write"):
        return None

    file_path = tool_input.get("file_path")
    if not file_path:
        return None

    try:
        db = SessionDB()
        context = file_context(db, file_path)
    except Exception:
        return None

    if not context:
        return None

    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "additionalContext": f"# {context}",
        }
    }


def generate_hook_config() -> dict:
    """Generate Claude Code hook configuration JSON.

    Returns the hooks section to merge into settings.json.
    """
    hooks_dir = Path(__file__).parent
    pretool_script = hooks_dir / "pretool.sh"

    return {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Read|Edit|Write",
                    "hooks": [
                        {
                            "type": "command",
                            "command": str(pretool_script),
                        }
                    ],
                }
            ]
        }
    }


def install_hook(scope: str = "global") -> str:
    """Install Engram PreToolUse hook into Claude Code settings.

    Args:
        scope: "global" for ~/.claude/settings.json,
               "project" for .claude/settings.json
    """
    if scope == "project":
        settings_path = Path.cwd() / ".claude" / "settings.json"
    else:
        settings_path = Path.home() / ".claude" / "settings.json"

    # Ensure pretool.sh is executable
    hooks_dir = Path(__file__).parent
    pretool_script = hooks_dir / "pretool.sh"
    if pretool_script.exists():
        pretool_script.chmod(0o755)

    # Read existing settings
    existing: dict[str, Any] = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = {}

    hook_config = generate_hook_config()

    if "hooks" not in existing:
        existing["hooks"] = {}

    existing_hooks = existing["hooks"]
    new_pretool_hooks = hook_config["hooks"]["PreToolUse"]

    if "PreToolUse" in existing_hooks:
        kept = []
        for entry in existing_hooks["PreToolUse"]:
            hooks_list = entry.get("hooks", [])
            is_engram = any(
                "pretool.sh" in (h.get("command", "") or "")
                for h in hooks_list
            )
            if not is_engram:
                kept.append(entry)
        kept.extend(new_pretool_hooks)
        existing_hooks["PreToolUse"] = kept
    else:
        existing_hooks["PreToolUse"] = new_pretool_hooks

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(existing, indent=2) + "\n")

    return f"Engram hook installed to {settings_path}"
