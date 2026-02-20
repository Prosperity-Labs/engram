"""Tests for the Cursor adapter."""

from engram.adapters.cursor import CursorAdapter


class TestCursorAdapterParsing:
    def test_parse_file_edit_event(self):
        adapter = CursorAdapter()
        turn = adapter.parse_event({
            "hook_type": "afterFileEdit",
            "file_path": "/src/app.ts",
            "diff": "+const x = 1;",
            "timestamp": "2026-02-21T10:00:00Z",
        })
        assert turn is not None
        assert turn.role == "assistant"
        assert len(turn.tool_calls) == 1
        assert turn.tool_calls[0].name == "Edit"

    def test_parse_stop_event(self):
        adapter = CursorAdapter()
        turn = adapter.parse_event({
            "hook_type": "stop",
            "summary": "Fixed auth flow",
            "timestamp": "2026-02-21T10:05:00Z",
        })
        assert turn is not None
        assert turn.role == "summary"
        assert "auth" in turn.content.lower()

    def test_parse_shell_event(self):
        adapter = CursorAdapter()
        turn = adapter.parse_event({
            "hook_type": "afterShellExecution",
            "command": "npm test",
            "output": "3 passed",
            "timestamp": "2026-02-21T10:02:00Z",
        })
        assert turn is not None
        assert turn.tool_calls[0].name == "Bash"

    def test_discover_returns_list(self):
        adapter = CursorAdapter()
        sessions = adapter.discover_sessions()
        assert isinstance(sessions, list)
