"""Tests for the artifact trail parser."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from engram.artifact_trail import (
    ArtifactEvent,
    format_trail,
    parse_session_trail,
)


def _write_jsonl(path, entries):
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _make_assistant(ts, tool_uses):
    return {
        "type": "assistant",
        "timestamp": ts,
        "sessionId": "test-session",
        "message": {"content": tool_uses},
    }


def _make_user_results(ts, results):
    return {
        "type": "user",
        "timestamp": ts,
        "sessionId": "test-session",
        "message": {"content": results},
    }


class TestParseWrite:
    def test_write_event(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            _make_assistant("2026-03-01T10:00:00Z", [
                {
                    "type": "tool_use", "id": "tu_w1", "name": "Write",
                    "input": {"file_path": "/app/config.json", "content": '{"key": "value"}'},
                },
            ]),
            _make_user_results("2026-03-01T10:00:01Z", [
                {
                    "type": "tool_result", "tool_use_id": "tu_w1",
                    "content": "File created successfully at: /app/config.json",
                },
            ]),
        ])

        events = parse_session_trail(jsonl)
        assert len(events) == 1
        ev = events[0]
        assert ev.tool_type == "WRITE"
        assert ev.file_path == "/app/config.json"
        assert ev.new_content == '{"key": "value"}'
        assert ev.is_error is False
        assert ev.tool_use_id == "tu_w1"


class TestParseEdit:
    def test_edit_event(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            _make_assistant("2026-03-01T10:00:00Z", [
                {
                    "type": "tool_use", "id": "tu_e1", "name": "Edit",
                    "input": {
                        "file_path": "/src/app.ts",
                        "old_string": "const x = 1;",
                        "new_string": "const x = 2;\nconst y = 3;",
                        "replace_all": False,
                    },
                },
            ]),
            _make_user_results("2026-03-01T10:00:02Z", [
                {
                    "type": "tool_result", "tool_use_id": "tu_e1",
                    "content": "The file /src/app.ts has been updated successfully.",
                },
            ]),
        ])

        events = parse_session_trail(jsonl)
        assert len(events) == 1
        ev = events[0]
        assert ev.tool_type == "EDIT"
        assert ev.file_path == "/src/app.ts"
        assert ev.old_content == "const x = 1;"
        assert ev.new_content == "const x = 2;\nconst y = 3;"


class TestParseBash:
    def test_bash_success(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            _make_assistant("2026-03-01T10:00:00Z", [
                {
                    "type": "tool_use", "id": "tu_b1", "name": "Bash",
                    "input": {"command": "npm test", "description": "Run tests"},
                },
            ]),
            _make_user_results("2026-03-01T10:00:05Z", [
                {
                    "type": "tool_result", "tool_use_id": "tu_b1",
                    "content": "All 42 tests passed",
                },
            ]),
        ])

        events = parse_session_trail(jsonl)
        assert len(events) == 1
        ev = events[0]
        assert ev.tool_type == "BASH"
        assert ev.command == "npm test"
        assert ev.description == "Run tests"
        assert ev.exit_code == 0
        assert ev.stdout == "All 42 tests passed"
        assert ev.is_error is False

    def test_bash_error(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            _make_assistant("2026-03-01T10:00:00Z", [
                {
                    "type": "tool_use", "id": "tu_b2", "name": "Bash",
                    "input": {"command": "gcc main.c"},
                },
            ]),
            _make_user_results("2026-03-01T10:00:03Z", [
                {
                    "type": "tool_result", "tool_use_id": "tu_b2",
                    "content": "Exit code 2\nmain.c:5: error: undeclared variable",
                    "is_error": True,
                },
            ]),
        ])

        events = parse_session_trail(jsonl)
        ev = events[0]
        assert ev.exit_code == 2
        assert ev.is_error is True


class TestParseRead:
    def test_read_event(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            _make_assistant("2026-03-01T10:00:00Z", [
                {
                    "type": "tool_use", "id": "tu_r1", "name": "Read",
                    "input": {"file_path": "/src/validators.ts"},
                },
            ]),
            _make_user_results("2026-03-01T10:00:01Z", [
                {
                    "type": "tool_result", "tool_use_id": "tu_r1",
                    "content": "     1|export function validate() { ... }",
                },
            ]),
        ])

        events = parse_session_trail(jsonl)
        assert len(events) == 1
        ev = events[0]
        assert ev.tool_type == "READ"
        assert ev.file_path == "/src/validators.ts"


class TestExitCodeParsing:
    @pytest.mark.parametrize("content,expected_code,expected_error", [
        ("Exit code 1\nerror msg", 1, True),
        ("Exit code 0\nok", 0, False),
        ("Exit code 127\ncommand not found", 127, True),
    ])
    def test_exit_code_regex(self, tmp_path, content, expected_code, expected_error):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            _make_assistant("2026-03-01T10:00:00Z", [
                {
                    "type": "tool_use", "id": "tu_ec", "name": "Bash",
                    "input": {"command": "some_cmd"},
                },
            ]),
            _make_user_results("2026-03-01T10:00:01Z", [
                {
                    "type": "tool_result", "tool_use_id": "tu_ec",
                    "content": content,
                    "is_error": expected_code != 0,
                },
            ]),
        ])

        events = parse_session_trail(jsonl)
        ev = events[0]
        assert ev.exit_code == expected_code
        assert ev.is_error is expected_error


class TestToolResultMatching:
    def test_tool_use_to_result_matching(self, tmp_path):
        """tool_result blocks are matched to tool_use blocks via tool_use_id."""
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            _make_assistant("2026-03-01T10:00:00Z", [
                {
                    "type": "tool_use", "id": "tu_a", "name": "Read",
                    "input": {"file_path": "/a.ts"},
                },
                {
                    "type": "tool_use", "id": "tu_b", "name": "Read",
                    "input": {"file_path": "/b.ts"},
                },
            ]),
            _make_user_results("2026-03-01T10:00:01Z", [
                {
                    "type": "tool_result", "tool_use_id": "tu_a",
                    "content": "content of a",
                },
                {
                    "type": "tool_result", "tool_use_id": "tu_b",
                    "content": "content of b",
                    "is_error": True,
                },
            ]),
        ])

        events = parse_session_trail(jsonl)
        assert len(events) == 2
        by_id = {ev.tool_use_id: ev for ev in events}
        assert by_id["tu_a"].file_path == "/a.ts"
        assert by_id["tu_a"].is_error is False
        assert by_id["tu_b"].file_path == "/b.ts"
        assert by_id["tu_b"].is_error is True


class TestFormatTrail:
    def test_format_output(self):
        t0 = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
        events = [
            ArtifactEvent(
                sequence=1, timestamp=t0,
                tool_type="READ", file_path="/src/validators.ts",
            ),
            ArtifactEvent(
                sequence=2,
                timestamp=datetime(2026, 3, 1, 10, 0, 30, tzinfo=timezone.utc),
                tool_type="EDIT", file_path="/src/validators.ts",
                old_content="line1\nline2\nline3\nline4",
                new_content="line1\nnew2\nnew3\nnew4\nline5\nline6",
            ),
            ArtifactEvent(
                sequence=3,
                timestamp=datetime(2026, 3, 1, 10, 1, 10, tzinfo=timezone.utc),
                tool_type="BASH", file_path=None,
                command="npm test", exit_code=0,
            ),
        ]

        output = format_trail(events)
        lines = output.splitlines()
        assert len(lines) == 3
        assert "#001" in lines[0]
        assert "READ" in lines[0]
        assert "validators.ts" in lines[0]
        assert "#002" in lines[1]
        assert "EDIT" in lines[1]
        assert "+6/-4 lines" in lines[1]
        assert "#003" in lines[2]
        assert "BASH" in lines[2]
        assert "npm test" in lines[2]
        assert "exit 0" in lines[2]

    def test_format_empty(self):
        assert format_trail([]) == "No artifact events found."


class TestSequenceOrdering:
    def test_events_ordered_by_sequence(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            _make_assistant("2026-03-01T10:00:00Z", [
                {"type": "tool_use", "id": "tu_1", "name": "Read", "input": {"file_path": "/first.ts"}},
            ]),
            _make_assistant("2026-03-01T10:00:10Z", [
                {"type": "tool_use", "id": "tu_2", "name": "Edit", "input": {"file_path": "/second.ts", "old_string": "a", "new_string": "b"}},
            ]),
            _make_assistant("2026-03-01T10:00:20Z", [
                {"type": "tool_use", "id": "tu_3", "name": "Bash", "input": {"command": "npm test"}},
            ]),
        ])

        events = parse_session_trail(jsonl)
        assert [ev.sequence for ev in events] == [1, 2, 3]
        assert events[0].tool_type == "READ"
        assert events[1].tool_type == "EDIT"
        assert events[2].tool_type == "BASH"


class TestMalformedInput:
    def test_skips_bad_json_lines(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        with open(jsonl, "w") as f:
            f.write("not valid json\n")
            f.write(json.dumps(_make_assistant("2026-03-01T10:00:00Z", [
                {"type": "tool_use", "id": "tu_ok", "name": "Read", "input": {"file_path": "/ok.ts"}},
            ])) + "\n")

        events = parse_session_trail(jsonl)
        assert len(events) == 1

    def test_ignores_non_tool_types(self, tmp_path):
        jsonl = tmp_path / "session.jsonl"
        _write_jsonl(jsonl, [
            {"type": "progress", "timestamp": "2026-03-01T10:00:00Z", "message": {"content": []}},
            {"type": "summary", "timestamp": "2026-03-01T10:00:00Z", "message": {"content": [{"type": "text", "text": "summary"}]}},
            _make_assistant("2026-03-01T10:00:05Z", [
                {"type": "tool_use", "id": "tu_x", "name": "Read", "input": {"file_path": "/x.ts"}},
            ]),
        ])

        events = parse_session_trail(jsonl)
        assert len(events) == 1
        assert events[0].tool_type == "READ"
