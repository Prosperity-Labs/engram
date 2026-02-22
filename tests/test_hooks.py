"""Tests for engram.hooks — PreToolUse hook module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engram.hooks import (
    file_context,
    generate_hook_config,
    handle_pretool_hook,
    install_hook,
    last_session_summary,
)
from engram.recall.artifact_extractor import ArtifactExtractor
from engram.recall.session_db import SessionDB


@pytest.fixture
def hook_db(tmp_db):
    """DB seeded with sessions and artifacts for hook testing."""
    db = tmp_db

    # Create the artifacts table
    extractor = ArtifactExtractor(db)

    with db._connect() as conn:
        # Insert 3 sessions for project "hook-project"
        for i in range(3):
            session_id = f"hook-session-{i:03d}"
            conn.execute(
                """INSERT INTO sessions
                   (session_id, filepath, project, message_count, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    f"/tmp/{session_id}.jsonl",
                    "hook-project",
                    20 + i * 10,
                    f"2026-02-{18+i}T10:00:00Z",
                    f"2026-02-{18+i}T14:00:00Z",
                ),
            )

            # File reads
            for seq in range(5):
                conn.execute(
                    """INSERT OR IGNORE INTO artifacts
                       (session_id, artifact_type, target, tool_name, sequence, context)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (session_id, "file_read", "/src/endpoints.ts", "Read", seq + i * 100, None),
                )
            # File writes
            conn.execute(
                """INSERT OR IGNORE INTO artifacts
                   (session_id, artifact_type, target, tool_name, sequence, context)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, "file_write", "/src/endpoints.ts", "Edit", 50 + i, None),
            )
            # Errors on endpoints.ts
            if i < 2:
                conn.execute(
                    """INSERT OR IGNORE INTO artifacts
                       (session_id, artifact_type, target, tool_name, sequence, context)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        "error",
                        "/src/endpoints.ts",
                        None,
                        90 + i,
                        "CORS header missing on /api/users",
                    ),
                )

            # Commands
            conn.execute(
                """INSERT OR IGNORE INTO artifacts
                   (session_id, artifact_type, target, tool_name, sequence, context)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, "command", "npm test", "Bash", 60 + i, None),
            )

            # Some messages for the session
            for j in range(5):
                conn.execute(
                    """INSERT OR IGNORE INTO messages
                       (session_id, sequence, role, content, timestamp, tool_name,
                        token_usage_in, token_usage_out, cache_read_tokens, cache_create_tokens)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_id, j, "assistant",
                        f"Working on feature {j}",
                        f"2026-02-{18+i}T10:{j:02d}:00Z",
                        "Read" if j % 2 == 0 else None,
                        1000, 100, 500, 0,
                    ),
                )

    return db


class TestFileContext:
    def test_file_with_history(self, hook_db):
        result = file_context(hook_db, "/src/endpoints.ts")
        assert result is not None
        assert "endpoints.ts" in result
        assert "reads" in result
        assert "writes" in result
        assert "errors" in result
        assert "sessions" in result

    def test_file_no_history(self, hook_db):
        result = file_context(hook_db, "/nonexistent/file.py")
        assert result is None

    def test_includes_last_error(self, hook_db):
        result = file_context(hook_db, "/src/endpoints.ts")
        assert result is not None
        assert "CORS" in result

    def test_session_count(self, hook_db):
        result = file_context(hook_db, "/src/endpoints.ts")
        assert result is not None
        assert "3 sessions" in result


class TestLastSessionSummary:
    def test_returns_summary(self, hook_db):
        result = last_session_summary(hook_db, "hook-project")
        assert result is not None
        assert "Last session" in result
        assert "messages" in result

    def test_no_sessions(self, hook_db):
        result = last_session_summary(hook_db, "nonexistent-project")
        assert result is None

    def test_contains_date(self, hook_db):
        result = last_session_summary(hook_db, "hook-project")
        assert result is not None
        assert "2026-02-20" in result


class TestHandlePretoolHook:
    def test_read_tool_with_history(self, hook_db, monkeypatch):
        # Monkeypatch SessionDB to use our test DB
        monkeypatch.setattr("engram.hooks.SessionDB", lambda *a, **kw: hook_db)

        stdin_json = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/src/endpoints.ts"},
        }
        result = handle_pretool_hook(stdin_json)
        assert result is not None
        assert "hookSpecificOutput" in result
        assert result["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
        assert "endpoints.ts" in result["hookSpecificOutput"]["additionalContext"]

    def test_edit_tool_with_history(self, hook_db, monkeypatch):
        monkeypatch.setattr("engram.hooks.SessionDB", lambda *a, **kw: hook_db)

        stdin_json = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/src/endpoints.ts"},
        }
        result = handle_pretool_hook(stdin_json)
        assert result is not None
        assert "hookSpecificOutput" in result

    def test_bash_tool_no_match(self, hook_db, monkeypatch):
        monkeypatch.setattr("engram.hooks.SessionDB", lambda *a, **kw: hook_db)

        stdin_json = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm test"},
        }
        result = handle_pretool_hook(stdin_json)
        assert result is None

    def test_read_tool_no_history(self, hook_db, monkeypatch):
        monkeypatch.setattr("engram.hooks.SessionDB", lambda *a, **kw: hook_db)

        stdin_json = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/totally/new/file.ts"},
        }
        result = handle_pretool_hook(stdin_json)
        assert result is None

    def test_no_file_path(self, hook_db, monkeypatch):
        monkeypatch.setattr("engram.hooks.SessionDB", lambda *a, **kw: hook_db)

        stdin_json = {
            "tool_name": "Read",
            "tool_input": {},
        }
        result = handle_pretool_hook(stdin_json)
        assert result is None

    def test_glob_tool_ignored(self, hook_db, monkeypatch):
        monkeypatch.setattr("engram.hooks.SessionDB", lambda *a, **kw: hook_db)

        stdin_json = {
            "tool_name": "Glob",
            "tool_input": {"pattern": "**/*.ts"},
        }
        result = handle_pretool_hook(stdin_json)
        assert result is None


class TestGenerateHookConfig:
    def test_produces_valid_config(self):
        config = generate_hook_config()
        assert "hooks" in config
        assert "PreToolUse" in config["hooks"]
        entries = config["hooks"]["PreToolUse"]
        assert len(entries) == 1
        assert entries[0]["matcher"] == "Read|Edit|Write"
        assert len(entries[0]["hooks"]) == 1
        assert entries[0]["hooks"][0]["type"] == "command"
        assert "pretool.sh" in entries[0]["hooks"][0]["command"]

    def test_config_is_json_serializable(self):
        config = generate_hook_config()
        serialized = json.dumps(config)
        assert isinstance(serialized, str)
        roundtrip = json.loads(serialized)
        assert roundtrip == config


class TestInstallHook:
    def test_creates_config(self, tmp_path, monkeypatch):
        settings_path = tmp_path / ".claude" / "settings.json"
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        result = install_hook(scope="global")
        assert "installed" in result.lower() or "settings.json" in result
        assert settings_path.exists()

        config = json.loads(settings_path.read_text())
        assert "hooks" in config
        assert "PreToolUse" in config["hooks"]

    def test_preserves_existing_settings(self, tmp_path, monkeypatch):
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir(parents=True)
        settings_path = settings_dir / "settings.json"
        settings_path.write_text(json.dumps({
            "permissions": {"allow": ["Read"]},
            "hooks": {
                "PostToolUse": [{"matcher": "Bash", "hooks": []}]
            },
        }))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        install_hook(scope="global")

        config = json.loads(settings_path.read_text())
        # Existing settings preserved
        assert "permissions" in config
        assert config["permissions"]["allow"] == ["Read"]
        # Existing hooks preserved
        assert "PostToolUse" in config["hooks"]
        # New hook added
        assert "PreToolUse" in config["hooks"]

    def test_project_scope(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = install_hook(scope="project")
        settings_path = tmp_path / ".claude" / "settings.json"
        assert settings_path.exists()
        assert "settings.json" in result

    def test_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        install_hook(scope="global")
        install_hook(scope="global")

        settings_path = tmp_path / ".claude" / "settings.json"
        config = json.loads(settings_path.read_text())
        # Should only have one engram PreToolUse entry, not duplicates
        pretool_entries = config["hooks"]["PreToolUse"]
        engram_entries = [
            e for e in pretool_entries
            if any("pretool.sh" in (h.get("command", "") or "") for h in e.get("hooks", []))
        ]
        assert len(engram_entries) == 1
