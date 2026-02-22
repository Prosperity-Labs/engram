import pytest

from engram.brief import (
    _architecture_patterns,
    _common_errors,
    _cost_profile,
    _key_files,
    _project_overview,
    generate_brief,
)
from engram.recall.artifact_extractor import ArtifactExtractor
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

