"""Tests for the Engram MCP server tools."""

from __future__ import annotations

import json

import pytest

from engram.recall.session_db import SessionDB
from engram.recall.artifact_extractor import ArtifactExtractor


@pytest.fixture
def populated_db(tmp_db):
    """DB with a session, messages, and artifacts for testing MCP tools."""
    db = tmp_db

    with db._connect() as conn:
        conn.execute(
            """INSERT INTO sessions
               (session_id, filepath, project, message_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("sess-001", "/tmp/test.jsonl", "my-app", 6,
             "2026-02-20T10:00:00Z", "2026-02-20T11:00:00Z"),
        )
        conn.execute(
            """INSERT INTO sessions
               (session_id, filepath, project, message_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("sess-002", "/tmp/test2.jsonl", "my-app", 3,
             "2026-02-21T08:00:00Z", "2026-02-21T09:00:00Z"),
        )

        messages = [
            ("sess-001", 0, "user", "Fix the login bug", "2026-02-20T10:00:00Z",
             None, 100, 0, 0, 0),
            ("sess-001", 1, "assistant", "I'll look at the login handler.",
             "2026-02-20T10:00:05Z", None, 1500, 200, 500, 0),
            ("sess-001", 2, "assistant",
             "tool_use:Read(file_path=…)",
             "2026-02-20T10:00:05Z", "Read", 0, 0, 0, 0),
            ("sess-001", 3, "assistant", "Found the bug. Fixing now.",
             "2026-02-20T10:00:15Z", None, 3000, 150, 0, 0),
            ("sess-001", 4, "assistant",
             "tool_use:Edit(file_path=…)",
             "2026-02-20T10:00:15Z", "Edit", 0, 0, 0, 0),
            ("sess-001", 5, "assistant",
             "Error: CORS issue with /api/auth endpoint",
             "2026-02-20T10:00:20Z", None, 500, 50, 0, 0),
            ("sess-002", 0, "user", "Add dashboard feature",
             "2026-02-21T08:00:00Z", None, 200, 0, 0, 0),
            ("sess-002", 1, "assistant",
             "tool_use:Read(file_path=…)",
             "2026-02-21T08:00:05Z", "Read", 1000, 100, 0, 0),
            ("sess-002", 2, "assistant", "I chose to use React because it fits the architecture.",
             "2026-02-21T08:00:10Z", None, 800, 300, 0, 0),
        ]
        conn.executemany(
            """INSERT INTO messages
               (session_id, sequence, role, content, timestamp,
                tool_name, token_usage_in, token_usage_out,
                cache_read_tokens, cache_create_tokens)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            messages,
        )

    # Create artifacts table and insert test artifacts
    extractor = ArtifactExtractor(db)
    with db._connect() as conn:
        artifacts = [
            ("sess-001", "file_read", "/src/auth/login.ts", "Read", 2, None),
            ("sess-001", "file_write", "/src/auth/login.ts", "Edit", 4, None),
            ("sess-001", "error", "/src/auth/login.ts", None, 5,
             "CORS issue with /api/auth endpoint"),
            ("sess-002", "file_read", "/src/dashboard/index.tsx", "Read", 1, None),
        ]
        conn.executemany(
            """INSERT INTO artifacts
               (session_id, artifact_type, target, tool_name, sequence, context)
               VALUES (?, ?, ?, ?, ?, ?)""",
            artifacts,
        )

    return db


# Patch _get_db to use our test DB
@pytest.fixture(autouse=True)
def _patch_get_db(populated_db, monkeypatch):
    monkeypatch.setattr(
        "engram.mcp_server._get_db", lambda: populated_db
    )


# ── Tool Tests ───────────────────────────────────────────────────────


class TestEngramSearch:
    def test_search_returns_results(self):
        from engram.mcp_server import engram_search
        result = json.loads(engram_search("login"))
        assert result["count"] > 0
        assert len(result["results"]) > 0

    def test_search_no_results(self):
        from engram.mcp_server import engram_search
        result = json.loads(engram_search("zzz_nonexistent_zzz"))
        assert result["results"] == []
        assert "No results" in result["message"]

    def test_search_with_project_filter(self):
        from engram.mcp_server import engram_search
        result = json.loads(engram_search("login", project="my-app"))
        for r in result["results"]:
            assert r["project"] == "my-app"

    def test_search_with_limit(self):
        from engram.mcp_server import engram_search
        result = json.loads(engram_search("login", limit=1))
        assert len(result["results"]) <= 1


class TestEngramFileHistory:
    def test_file_with_history(self):
        from engram.mcp_server import engram_file_history
        result = json.loads(engram_file_history("/src/auth/login.ts"))
        assert result["file_path"] == "/src/auth/login.ts"
        assert "login.ts" in result["summary"]

    def test_file_without_history(self):
        from engram.mcp_server import engram_file_history
        result = json.loads(engram_file_history("/nonexistent/file.py"))
        assert "No history" in result["summary"]


class TestEngramSessionList:
    def test_list_all_sessions(self):
        from engram.mcp_server import engram_session_list
        result = json.loads(engram_session_list())
        assert result["count"] == 2
        assert len(result["sessions"]) == 2

    def test_list_with_project_filter(self):
        from engram.mcp_server import engram_session_list
        result = json.loads(engram_session_list(project="my-app"))
        assert result["count"] == 2
        for s in result["sessions"]:
            assert s["project"] == "my-app"

    def test_list_with_limit(self):
        from engram.mcp_server import engram_session_list
        result = json.loads(engram_session_list(limit=1))
        assert len(result["sessions"]) == 1


class TestEngramProjectBrief:
    def test_slim_brief(self):
        from engram.mcp_server import engram_project_brief
        result = engram_project_brief("my-app", slim=True)
        assert "my-app" in result
        assert "Engram Brief" in result

    def test_full_brief(self):
        from engram.mcp_server import engram_project_brief
        result = engram_project_brief("my-app", slim=False)
        assert "Project Brief" in result
        assert "my-app" in result


class TestEngramDangerZones:
    def test_danger_zones_with_data(self):
        from engram.mcp_server import engram_danger_zones
        result = json.loads(engram_danger_zones("my-app"))
        assert result["project"] == "my-app"
        assert isinstance(result["danger_zones"], list)

    def test_danger_zones_empty_project(self):
        from engram.mcp_server import engram_danger_zones
        result = json.loads(engram_danger_zones("nonexistent-project"))
        assert result["danger_zones"] == []


class TestEngramArtifacts:
    def test_query_all_artifacts(self):
        from engram.mcp_server import engram_artifacts
        result = json.loads(engram_artifacts())
        assert result["count"] > 0

    def test_query_by_session(self):
        from engram.mcp_server import engram_artifacts
        result = json.loads(engram_artifacts(session_id="sess-001"))
        assert result["count"] > 0
        for a in result["artifacts"]:
            assert a["session_id"] == "sess-001"

    def test_query_by_type(self):
        from engram.mcp_server import engram_artifacts
        result = json.loads(engram_artifacts(artifact_type="file_read"))
        for a in result["artifacts"]:
            assert a["artifact_type"] == "file_read"


class TestEngramSessionStats:
    def test_all_project_stats(self):
        from engram.mcp_server import engram_session_stats
        result = json.loads(engram_session_stats())
        assert isinstance(result["stats"], list)

    def test_single_session_stats(self):
        from engram.mcp_server import engram_session_stats
        result = json.loads(engram_session_stats(session_id="sess-001"))
        stats = result["stats"]
        assert stats["messages"] == 6

    def test_stats_with_project_filter(self):
        from engram.mcp_server import engram_session_stats
        result = json.loads(engram_session_stats(project="my-app"))
        for s in result["stats"]:
            assert s["project"] == "my-app"


class TestEngramInsights:
    def test_insights_returns_data(self):
        from engram.mcp_server import engram_insights
        result = json.loads(engram_insights())
        assert "knowledge_base" in result
        assert "tool_usage" in result
        assert "cache_efficiency" in result
        assert result["knowledge_base"]["total_sessions"] == 2


# ── Resource Test ────────────────────────────────────────────────────

class TestListProjects:
    def test_list_projects(self):
        from engram.mcp_server import list_projects
        result = json.loads(list_projects())
        assert len(result["projects"]) == 1
        assert result["projects"][0]["project"] == "my-app"
        assert result["projects"][0]["sessions"] == 2
