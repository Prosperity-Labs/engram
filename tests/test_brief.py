import pytest

from engram.brief import (
    _architecture_patterns,
    _common_errors,
    _cost_profile,
    _key_files,
    _project_overview,
    generate_brief,
)
from engram.recall.artifact_extractor import ArtifactExtractor, _extract_error_message
from engram.recall.session_db import SessionDB


@pytest.fixture
def brief_db(tmp_db):
    """DB seeded with sessions, messages, and artifacts for brief testing."""
    db = tmp_db

    # Insert 3 sessions for project "test-project"
    for i in range(3):
        session_id = f"brief-test-session-{i:03d}"
        with db._connect() as conn:
            conn.execute(
                """INSERT INTO sessions
                   (session_id, filepath, project, message_count, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    f"/tmp/{session_id}.jsonl",
                    "test-project",
                    10 + i * 5,
                    f"2026-02-{18+i}T10:00:00Z",
                    f"2026-02-{18+i}T11:00:00Z",
                ),
            )

            # Messages with tool calls
            messages = [
                (
                    session_id,
                    j,
                    "assistant",
                    f'{{"file_path": "/src/app.ts"}}' if j % 3 == 0 else f"Working on feature {j}",
                    f"2026-02-{18+i}T10:{j:02d}:00Z",
                    "Read" if j % 3 == 0 else ("Edit" if j % 3 == 1 else None),
                    1000 * (j + 1),
                    100 * (j + 1),
                    500,
                    0,
                )
                for j in range(10 + i * 5)
            ]
            conn.executemany(
                """INSERT INTO messages
                   (session_id, sequence, role, content, timestamp,
                    tool_name, token_usage_in, token_usage_out,
                    cache_read_tokens, cache_create_tokens)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                messages,
            )

    # Initialize artifacts table and insert test artifacts
    extractor = ArtifactExtractor(db)
    with db._connect() as conn:
        for i in range(3):
            session_id = f"brief-test-session-{i:03d}"
            # File reads
            for path in ["/src/app.ts", "/src/lib/types.ts", "/src/db.py"]:
                for seq in range(3):
                    conn.execute(
                        """INSERT OR IGNORE INTO artifacts
                           (session_id, artifact_type, target, tool_name, sequence)
                           VALUES (?, ?, ?, ?, ?)""",
                        (session_id, "file_read", path, "Read", seq + i * 10),
                    )
            # File writes
            conn.execute(
                """INSERT OR IGNORE INTO artifacts
                   (session_id, artifact_type, target, tool_name, sequence)
                   VALUES (?, ?, ?, ?, ?)""",
                (session_id, "file_write", "/src/app.ts", "Edit", 50 + i),
            )
            # Errors
            if i < 2:
                conn.execute(
                    """INSERT OR IGNORE INTO artifacts
                       (session_id, artifact_type, target, tool_name, sequence)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        "error",
                        "TypeError: Cannot read property 'id' of undefined",
                        None,
                        90 + i,
                    ),
                )

    return db


class TestProjectOverview:
    def test_returns_correct_shape(self, brief_db):
        result = _project_overview(brief_db, "test-project")
        assert result["sessions"] == 3
        assert result["messages"] > 0
        assert result["tokens_in"] > 0
        assert result["tokens_out"] > 0
        assert result["cost_estimate"] > 0
        assert result["first_session"] is not None
        assert result["last_session"] is not None

    def test_missing_project_returns_zeros(self, brief_db):
        result = _project_overview(brief_db, "nonexistent")
        assert result["sessions"] == 0
        assert result["messages"] == 0


class TestKeyFiles:
    def test_returns_most_read(self, brief_db):
        result = _key_files(brief_db, "test-project")
        assert len(result["most_read"]) > 0
        assert all("path" in f and "count" in f and "sessions" in f for f in result["most_read"])

    def test_returns_most_modified(self, brief_db):
        result = _key_files(brief_db, "test-project")
        assert len(result["most_modified"]) > 0
        # /src/app.ts should be in most modified
        paths = [f["path"] for f in result["most_modified"]]
        assert "/src/app.ts" in paths

    def test_empty_project(self, brief_db):
        result = _key_files(brief_db, "nonexistent")
        assert result["most_read"] == []
        assert result["most_modified"] == []


class TestCommonErrors:
    def test_finds_errors(self, brief_db):
        result = _common_errors(brief_db, "test-project")
        assert len(result) > 0
        assert result[0]["occurrences"] >= 1
        assert result[0]["sessions"] >= 1

    def test_empty_project(self, brief_db):
        result = _common_errors(brief_db, "nonexistent")
        assert result == []


class TestCostProfile:
    def test_returns_percentages(self, brief_db):
        result = _cost_profile(brief_db, "test-project")
        assert "exploration_pct" in result
        assert "mutation_pct" in result
        assert "execution_pct" in result
        assert isinstance(result["exploration_pct"], int)


class TestGenerateBrief:
    def test_markdown_output(self, brief_db):
        result = generate_brief(brief_db, "test-project", format="markdown")
        assert "# Project Brief: test-project" in result
        assert "## Overview" in result
        assert "## Key Files" in result
        assert "## Cost Profile" in result

    def test_json_output(self, brief_db):
        import json

        result = generate_brief(brief_db, "test-project", format="json")
        data = json.loads(result)
        assert data["project"] == "test-project"
        assert "overview" in data
        assert "key_files" in data
        assert "cost_profile" in data

    def test_markdown_length(self, brief_db):
        result = generate_brief(brief_db, "test-project", format="markdown")
        # Brief should be compact — under 4000 chars (roughly 500-2000 tokens)
        assert len(result) < 4000
        assert len(result) > 100  # but not empty

    def test_nonexistent_project(self, brief_db):
        result = generate_brief(brief_db, "nonexistent", format="markdown")
        assert "# Project Brief: nonexistent" in result
        assert "0" in result  # should show 0 sessions


class TestExtractErrorMessage:
    """Unit tests for _extract_error_message — the fix for raw JSON in recurring errors."""

    def test_plain_text_error(self):
        msg = "Error: Module not found — cannot resolve 'foo'"
        result = _extract_error_message(msg)
        assert result == msg

    def test_plain_text_no_error(self):
        assert _extract_error_message("All tests passed") is None

    def test_empty_and_none(self):
        assert _extract_error_message("") is None
        assert _extract_error_message(None) is None

    def test_json_tool_use_only_skipped(self):
        """Pure tool_use content should NOT produce an error, even if params contain 'error'."""
        import json

        content = json.dumps(
            [
                {
                    "type": "tool_use",
                    "id": "tu_01",
                    "name": "Read",
                    "input": {"file_path": "/src/error_handler.ts"},
                }
            ]
        )
        assert _extract_error_message(content) is None

    def test_json_text_block_with_error(self):
        """Text block containing an error message should be extracted."""
        import json

        content = json.dumps(
            [
                {"type": "text", "text": "Error: CORS policy blocked the request"},
                {
                    "type": "tool_use",
                    "id": "tu_02",
                    "name": "Edit",
                    "input": {"file_path": "/src/server.ts"},
                },
            ]
        )
        result = _extract_error_message(content)
        assert result is not None
        assert "CORS policy" in result
        assert "tool_use" not in result

    def test_json_text_block_no_error(self):
        """Text block without error keywords should return None."""
        import json

        content = json.dumps(
            [
                {"type": "text", "text": "I'll fix the login handler now."},
                {
                    "type": "tool_use",
                    "id": "tu_03",
                    "name": "Read",
                    "input": {"file_path": "/src/login.ts"},
                },
            ]
        )
        assert _extract_error_message(content) is None

    def test_truncates_long_error(self):
        msg = "Error: " + "x" * 300
        result = _extract_error_message(msg)
        assert len(result) == 200

    def test_single_tool_use_dict_skipped(self):
        """A single tool_use dict (not in array) should be skipped."""
        import json

        content = json.dumps(
            {"type": "tool_use", "id": "tu_04", "name": "Bash", "input": {"command": "echo error"}}
        )
        assert _extract_error_message(content) is None


class TestErrorExtractionEndToEnd:
    """End-to-end: tool_use-only messages should not appear as errors in the brief."""

    def test_tool_use_json_not_stored_as_error(self, tmp_db):
        import json

        db = tmp_db
        session_id = "error-extraction-e2e"
        with db._connect() as conn:
            conn.execute(
                """INSERT INTO sessions
                   (session_id, filepath, project, message_count, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, "/tmp/test.jsonl", "test-project", 3,
                 "2026-02-20T10:00:00Z", "2026-02-20T11:00:00Z"),
            )
            # Message with tool_use JSON that happens to reference 'error_handler'
            tool_use_content = json.dumps([
                {
                    "type": "tool_use",
                    "id": "tu_01",
                    "name": "Read",
                    "input": {"file_path": "/src/error_handler.ts"},
                }
            ])
            # Message with real error text
            real_error = "TypeError: Cannot read property 'id' of undefined"
            conn.executemany(
                """INSERT INTO messages
                   (session_id, sequence, role, content, timestamp,
                    tool_name, token_usage_in, token_usage_out,
                    cache_read_tokens, cache_create_tokens)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (session_id, 0, "assistant", tool_use_content, None, "Read", 100, 50, 0, 0),
                    (session_id, 1, "assistant", real_error, None, None, 100, 50, 0, 0),
                ],
            )

        extractor = ArtifactExtractor(db)
        artifacts = extractor.extract_session(session_id)
        errors = [a for a in artifacts if a["artifact_type"] == "error"]

        assert len(errors) == 1
        assert "TypeError" in errors[0]["target"]
        assert "tool_use" not in errors[0]["target"]

