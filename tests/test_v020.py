"""Validation tests for Engram v0.2.0 features.

These tests run against ANY branch to score which agent's implementation
is most complete. Tests use pytest.importorskip and xfail markers so
missing modules produce skips rather than import errors.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from engram.recall.session_db import SessionDB


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    """Fresh SQLite database with sample data for testing."""
    db = SessionDB(db_path=tmp_path / "test_v020.db")

    # Insert sample sessions
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, filepath, project, message_count, file_size_bytes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("sess-001", "/tmp/sess-001.jsonl", "monra-app", 50, 102400, "2026-02-18T10:00:00Z", "2026-02-18T11:00:00Z"),
        )
        conn.execute(
            "INSERT INTO sessions (session_id, filepath, project, message_count, file_size_bytes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("sess-002", "/tmp/sess-002.jsonl", "engram", 30, 51200, "2026-02-19T14:00:00Z", "2026-02-19T15:00:00Z"),
        )

        # Insert sample messages for sess-001
        messages = [
            ("sess-001", 0, "user", "Fix the login bug", "2026-02-18T10:00:00Z", None, 100, 0, 0, 0),
            ("sess-001", 1, "assistant", "I'll look at the login handler.", "2026-02-18T10:00:05Z", None, 1500, 200, 500, 0),
            ("sess-001", 2, "assistant", 'tool_use:Read(file_path=/src/auth/login.ts, limit=100)', "2026-02-18T10:00:06Z", "Read", 0, 0, 0, 0),
            ("sess-001", 3, "assistant", "Found the bug. Fixing now.", "2026-02-18T10:00:10Z", None, 3000, 150, 0, 0),
            ("sess-001", 4, "assistant", 'tool_use:Edit(file_path=/src/auth/login.ts, old_string=old, new_string=new)', "2026-02-18T10:00:11Z", "Edit", 0, 0, 0, 0),
            ("sess-001", 5, "assistant", 'tool_use:Bash(command=npm test)', "2026-02-18T10:00:15Z", "Bash", 500, 50, 0, 0),
            ("sess-001", 6, "assistant", "Error: test failed for login module", "2026-02-18T10:00:20Z", None, 200, 100, 0, 0),
            ("sess-001", 7, "assistant", 'tool_use:Edit(file_path=/src/auth/login.ts, old_string=bad, new_string=good)', "2026-02-18T10:00:25Z", "Edit", 0, 0, 0, 0),
            ("sess-001", 8, "assistant", 'tool_use:Bash(command=npm test)', "2026-02-18T10:00:30Z", "Bash", 500, 50, 0, 0),
            ("sess-001", 9, "assistant", "All tests pass now.", "2026-02-18T10:00:35Z", None, 200, 100, 0, 0),
        ]
        # Messages for sess-002
        messages += [
            ("sess-002", 0, "user", "Add stats command", "2026-02-19T14:00:00Z", None, 100, 0, 0, 0),
            ("sess-002", 1, "assistant", 'tool_use:Read(file_path=/workspace/engram/cli.py)', "2026-02-19T14:00:05Z", "Read", 1000, 100, 0, 0),
            ("sess-002", 2, "assistant", 'tool_use:Grep(pattern=def cmd_, path=/workspace/engram/)', "2026-02-19T14:00:10Z", "Grep", 500, 50, 0, 0),
            ("sess-002", 3, "assistant", 'tool_use:Write(file_path=/workspace/engram/stats.py)', "2026-02-19T14:00:15Z", "Write", 800, 200, 0, 0),
            ("sess-002", 4, "assistant", "Created the stats module.", "2026-02-19T14:00:20Z", None, 200, 100, 0, 0),
        ]

        conn.executemany(
            """INSERT INTO messages
               (session_id, sequence, role, content, timestamp,
                tool_name, token_usage_in, token_usage_out,
                cache_read_tokens, cache_create_tokens)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            messages,
        )

    return db


@pytest.fixture
def session_with_tools(tmp_db):
    """Return the tmp_db — sessions already have tool-using messages."""
    return tmp_db


# ===========================================================================
# Test 1: clean_project_name
# ===========================================================================

class TestCleanProjectName:
    """Test the project name cleaning function."""

    def _get_fn(self):
        """Import clean_project_name, skip if not implemented."""
        try:
            from engram.recall.session_db import clean_project_name
            return clean_project_name
        except ImportError:
            pytest.skip("clean_project_name not implemented yet")

    def test_standard_development_path(self):
        fn = self._get_fn()
        assert fn("-home-prosperitylabs-Desktop-development-monra-app") == "monra-app"

    def test_nested_project_path(self):
        fn = self._get_fn()
        result = fn("-home-prosperitylabs-Desktop-development-monra-app-monra-core")
        assert result == "monra-app/monra-core"

    def test_compound_hyphenated_name(self):
        fn = self._get_fn()
        assert fn("-home-prosperitylabs-Desktop-development-music-nft-platform") == "music-nft-platform"

    def test_development_dir_only(self):
        fn = self._get_fn()
        assert fn("-home-prosperitylabs-Desktop-development") == "development"

    def test_already_clean_short(self):
        fn = self._get_fn()
        assert fn("app") == "app"

    def test_already_clean_word(self):
        fn = self._get_fn()
        assert fn("graph") == "graph"

    def test_empty_string(self):
        fn = self._get_fn()
        assert fn("") == ""

    def test_plugins_path(self):
        fn = self._get_fn()
        result = fn("-home-prosperitylabs--claude-plugins-marketplaces-thedotmack-plugin")
        assert result == "thedotmack-plugin"


class TestCleanAllProjectNames:
    """Test the bulk project name update method."""

    def test_clean_all_updates_dirty_names(self, tmp_db):
        if not hasattr(tmp_db, "clean_all_project_names"):
            pytest.skip("clean_all_project_names not implemented yet")

        # Insert a session with an ugly project name
        with tmp_db._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, filepath, project, message_count) VALUES (?, ?, ?, ?)",
                ("dirty-001", "/tmp/dirty.jsonl", "-home-prosperitylabs-Desktop-development-monra-app", 10),
            )

        count = tmp_db.clean_all_project_names()
        assert count >= 1

        # Verify it was cleaned
        with tmp_db._connect() as conn:
            row = conn.execute("SELECT project FROM sessions WHERE session_id = 'dirty-001'").fetchone()
            assert row["project"] == "monra-app"


# ===========================================================================
# Test 2: compute_project_stats
# ===========================================================================

class TestProjectStats:
    """Test per-project statistics computation."""

    def _get_fn(self):
        try:
            from engram.stats import compute_project_stats
            return compute_project_stats
        except ImportError:
            pytest.skip("engram.stats not implemented yet")

    def test_returns_list(self, tmp_db):
        fn = self._get_fn()
        stats = fn(tmp_db)
        assert isinstance(stats, list)

    def test_returns_nonempty(self, tmp_db):
        fn = self._get_fn()
        stats = fn(tmp_db)
        assert len(stats) > 0

    def test_required_keys(self, tmp_db):
        fn = self._get_fn()
        stats = fn(tmp_db)
        required = {"project", "sessions", "messages", "tokens_in", "tokens_out",
                     "tool_calls", "error_messages", "error_rate",
                     "exploration_ratio", "mutation_ratio", "execution_ratio"}
        for s in stats:
            assert required.issubset(s.keys()), f"Missing keys: {required - s.keys()}"

    def test_ratios_bounded(self, tmp_db):
        fn = self._get_fn()
        stats = fn(tmp_db)
        for s in stats:
            assert 0 <= s["error_rate"] <= 1, f"error_rate out of range: {s['error_rate']}"
            assert 0 <= s["exploration_ratio"] <= 1, f"exploration_ratio out of range: {s['exploration_ratio']}"
            assert 0 <= s["mutation_ratio"] <= 1, f"mutation_ratio out of range: {s['mutation_ratio']}"
            assert 0 <= s["execution_ratio"] <= 1, f"execution_ratio out of range: {s['execution_ratio']}"

    def test_sessions_positive(self, tmp_db):
        fn = self._get_fn()
        stats = fn(tmp_db)
        assert all(s["sessions"] > 0 for s in stats)


class TestRenderProjectStats:
    """Test terminal rendering of stats."""

    def test_render_contains_header_info(self, tmp_db):
        try:
            from engram.stats import compute_project_stats, render_project_stats
        except ImportError:
            pytest.skip("engram.stats not implemented yet")

        stats = compute_project_stats(tmp_db)
        rendered = render_project_stats(stats)
        assert isinstance(rendered, str)
        assert len(rendered) > 0
        # Should mention sessions somewhere
        assert "session" in rendered.lower() or "monra" in rendered.lower()


# ===========================================================================
# Test 3: list_sessions
# ===========================================================================

class TestListSessions:
    """Test session listing functionality."""

    def _get_fn(self):
        try:
            from engram.sessions import list_sessions
            return list_sessions
        except ImportError:
            pytest.skip("engram.sessions not implemented yet")

    def test_returns_list(self, tmp_db):
        fn = self._get_fn()
        sessions = fn(tmp_db, limit=10)
        assert isinstance(sessions, list)

    def test_returns_nonempty(self, tmp_db):
        fn = self._get_fn()
        sessions = fn(tmp_db, limit=10)
        assert len(sessions) > 0

    def test_required_keys(self, tmp_db):
        fn = self._get_fn()
        sessions = fn(tmp_db, limit=10)
        required = {"session_id", "project", "message_count"}
        for s in sessions:
            assert required.issubset(s.keys()), f"Missing keys: {required - s.keys()}"

    def test_session_id_present(self, tmp_db):
        fn = self._get_fn()
        sessions = fn(tmp_db, limit=10)
        assert all("session_id" in s and s["session_id"] for s in sessions)

    def test_limit_respected(self, tmp_db):
        fn = self._get_fn()
        sessions = fn(tmp_db, limit=1)
        assert len(sessions) <= 1

    def test_project_filter(self, tmp_db):
        fn = self._get_fn()
        sessions = fn(tmp_db, project="monra-app", limit=50)
        assert all(s["project"] == "monra-app" for s in sessions)

    def test_min_messages_filter(self, tmp_db):
        fn = self._get_fn()
        sessions = fn(tmp_db, min_messages=40, limit=50)
        # sess-001 has 50 messages, sess-002 has 30
        assert all(s["message_count"] >= 40 for s in sessions)


class TestRenderSessions:
    """Test terminal rendering of session list."""

    def test_render_contains_header(self, tmp_db):
        try:
            from engram.sessions import list_sessions, render_sessions
        except ImportError:
            pytest.skip("engram.sessions not implemented yet")

        sessions = list_sessions(tmp_db, limit=10)
        rendered = render_sessions(sessions)
        assert isinstance(rendered, str)
        assert len(rendered) > 0


# ===========================================================================
# Test 4: ArtifactExtractor
# ===========================================================================

class TestArtifactExtractor:
    """Test artifact extraction from session messages."""

    def _get_cls(self):
        try:
            from engram.recall.artifact_extractor import ArtifactExtractor
            return ArtifactExtractor
        except ImportError:
            pytest.skip("engram.recall.artifact_extractor not implemented yet")

    def test_extract_session_returns_list(self, session_with_tools):
        cls = self._get_cls()
        extractor = cls(session_with_tools)
        artifacts = extractor.extract_session("sess-001")
        assert isinstance(artifacts, list)

    def test_extract_session_finds_artifacts(self, session_with_tools):
        cls = self._get_cls()
        extractor = cls(session_with_tools)
        artifacts = extractor.extract_session("sess-001")
        assert len(artifacts) > 0, "Should extract at least one artifact from tool-using messages"

    def test_artifact_has_required_fields(self, session_with_tools):
        cls = self._get_cls()
        extractor = cls(session_with_tools)
        artifacts = extractor.extract_session("sess-001")
        if not artifacts:
            pytest.skip("No artifacts extracted")
        required = {"session_id", "artifact_type", "target"}
        for a in artifacts:
            assert required.issubset(a.keys()), f"Missing keys: {required - a.keys()}"

    def test_artifact_types_valid(self, session_with_tools):
        cls = self._get_cls()
        extractor = cls(session_with_tools)
        artifacts = extractor.extract_session("sess-001")
        valid_types = {"file_read", "file_write", "file_create", "command", "api_call", "error"}
        for a in artifacts:
            assert a["artifact_type"] in valid_types, f"Invalid type: {a['artifact_type']}"

    def test_extract_all_returns_counts(self, session_with_tools):
        cls = self._get_cls()
        extractor = cls(session_with_tools)
        result = extractor.extract_all()
        assert "sessions_processed" in result
        assert "artifacts_extracted" in result
        assert result["sessions_processed"] > 0

    def test_get_artifacts_with_type_filter(self, session_with_tools):
        cls = self._get_cls()
        extractor = cls(session_with_tools)
        extractor.extract_all()
        # sess-001 has Edit tool calls -> file_write artifacts
        artifacts = extractor.get_artifacts(artifact_type="file_write")
        # If file_write was extracted, all should match
        for a in artifacts:
            assert a["artifact_type"] == "file_write"

    def test_summary_returns_dict(self, session_with_tools):
        cls = self._get_cls()
        extractor = cls(session_with_tools)
        extractor.extract_all()
        summary = extractor.summary("sess-001")
        assert isinstance(summary, dict)
        expected_keys = {"files_read", "files_written", "files_created", "commands", "api_calls", "errors"}
        assert expected_keys.issubset(summary.keys()), f"Missing keys: {expected_keys - summary.keys()}"


# ===========================================================================
# Test 5: Export (JSON/CSV)
# ===========================================================================

class TestExport:
    """Test data export functionality."""

    def _get_fns(self):
        try:
            from engram.export import export_events, export_sessions
            return export_events, export_sessions
        except ImportError:
            pytest.skip("engram.export not implemented yet")

    def test_export_events_json(self, tmp_db):
        export_events, _ = self._get_fns()
        result = export_events(tmp_db, format="json")
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) > 0
        assert "session_id" in data[0]

    def test_export_events_csv(self, tmp_db):
        import csv
        import io
        export_events, _ = self._get_fns()
        result = export_events(tmp_db, format="csv")
        reader = csv.DictReader(io.StringIO(result))
        rows = list(reader)
        assert len(rows) > 0
        assert "session_id" in rows[0]

    def test_export_sessions_json(self, tmp_db):
        _, export_sessions = self._get_fns()
        result = export_sessions(tmp_db, format="json")
        data = json.loads(result)
        assert isinstance(data, list)
        assert len(data) > 0

    def test_export_events_project_filter(self, tmp_db):
        export_events, _ = self._get_fns()
        result = export_events(tmp_db, format="json", project="monra-app")
        data = json.loads(result)
        # All returned events should be from monra-app sessions
        session_ids = {d["session_id"] for d in data}
        # sess-001 is monra-app, sess-002 is engram
        assert "sess-002" not in session_ids

    def test_export_to_file(self, tmp_db, tmp_path):
        export_events, _ = self._get_fns()
        outfile = str(tmp_path / "export.json")
        result = export_events(tmp_db, format="json", output=outfile)
        assert Path(outfile).exists()
        data = json.loads(Path(outfile).read_text())
        assert len(data) > 0
