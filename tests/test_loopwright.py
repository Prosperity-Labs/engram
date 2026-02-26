"""Tests for Loopwright tables: worktrees, checkpoints, correction_cycles."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from engram.recall.session_db import SessionDB


# ---------------------------------------------------------------------------
# Schema & migration tests
# ---------------------------------------------------------------------------


class TestSchemaCreation:
    """Verify new tables exist and have the right columns."""

    def test_worktrees_table_exists(self, tmp_db: SessionDB):
        with tmp_db._connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "worktrees" in tables
        assert "checkpoints" in tables
        assert "correction_cycles" in tables

    def test_fts_tables_exist(self, tmp_db: SessionDB):
        with tmp_db._connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "worktrees_fts" in tables
        assert "correction_cycles_fts" in tables

    def test_worktrees_columns(self, tmp_db: SessionDB):
        with tmp_db._connect() as conn:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(worktrees)").fetchall()
            }
        expected = {
            "id", "session_id", "branch_name", "base_branch", "status",
            "task_description", "ab_variant_label", "ab_brief_metadata",
            "results_json", "created_at", "resolved_at",
        }
        assert expected == cols

    def test_checkpoints_columns(self, tmp_db: SessionDB):
        with tmp_db._connect() as conn:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(checkpoints)").fetchall()
            }
        expected = {
            "id", "worktree_id", "session_id", "git_sha", "test_results",
            "artifact_snapshot", "graph_delta", "ab_variant_label",
            "created_at", "label",
        }
        assert expected == cols

    def test_correction_cycles_columns(self, tmp_db: SessionDB):
        with tmp_db._connect() as conn:
            cols = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(correction_cycles)"
                ).fetchall()
            }
        expected = {
            "id", "worktree_id", "cycle_number", "trigger_error",
            "error_context", "checkpoint_id", "agent_session_id",
            "outcome", "duration_seconds", "created_at",
        }
        assert expected == cols

    def test_idempotent_schema(self, tmp_path):
        """Running schema init twice must not raise."""
        db_path = tmp_path / "idempotent.db"
        db1 = SessionDB(db_path=db_path)
        db2 = SessionDB(db_path=db_path)
        with db2._connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "worktrees" in tables

    def test_indexes_exist(self, tmp_db: SessionDB):
        with tmp_db._connect() as conn:
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
        for idx_name in (
            "idx_worktrees_session",
            "idx_worktrees_status",
            "idx_checkpoints_worktree",
            "idx_checkpoints_session",
            "idx_correction_cycles_worktree",
            "idx_correction_cycles_checkpoint",
        ):
            assert idx_name in indexes, f"Missing index: {idx_name}"


# ---------------------------------------------------------------------------
# CRUD tests
# ---------------------------------------------------------------------------


class TestWorktreeCRUD:
    def test_create_worktree(self, tmp_db: SessionDB):
        wt_id = tmp_db.create_worktree(
            "feature/auth-fix",
            task_description="Fix OAuth token refresh",
        )
        assert isinstance(wt_id, int)
        assert wt_id > 0

    def test_get_worktree(self, tmp_db: SessionDB):
        wt_id = tmp_db.create_worktree(
            "feature/payments",
            base_branch="develop",
            task_description="Implement Stripe webhooks",
        )
        wt = tmp_db.get_worktree(wt_id)
        assert wt is not None
        assert wt["branch_name"] == "feature/payments"
        assert wt["base_branch"] == "develop"
        assert wt["status"] == "active"
        assert wt["task_description"] == "Implement Stripe webhooks"
        assert wt["resolved_at"] is None

    def test_get_worktree_not_found(self, tmp_db: SessionDB):
        assert tmp_db.get_worktree(999) is None

    def test_update_worktree_status(self, tmp_db: SessionDB):
        wt_id = tmp_db.create_worktree("feature/x", task_description="test")
        tmp_db.update_worktree_status(wt_id, "passed")
        wt = tmp_db.get_worktree(wt_id)
        assert wt["status"] == "passed"
        assert wt["resolved_at"] is not None

    def test_status_check_constraint(self, tmp_db: SessionDB):
        with pytest.raises(sqlite3.IntegrityError):
            tmp_db.create_worktree("feature/x", status="invalid_status")

    def test_worktree_with_session_id(self, tmp_db: SessionDB):
        with tmp_db._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, filepath) VALUES (?, ?)",
                ("sess-001", "/tmp/test.jsonl"),
            )
        wt_id = tmp_db.create_worktree(
            "feature/y",
            session_id="sess-001",
            task_description="Linked to session",
        )
        wt = tmp_db.get_worktree(wt_id)
        assert wt["session_id"] == "sess-001"


class TestCheckpointCRUD:
    def test_create_checkpoint(self, tmp_db: SessionDB):
        wt_id = tmp_db.create_worktree("feature/cp", task_description="checkpoint test")
        cp_id = tmp_db.create_checkpoint(
            wt_id,
            git_sha="abc123def456",
            test_results={"passed": 10, "failed": 0},
            artifact_snapshot=["src/main.py", "tests/test_main.py"],
            label="after auth fix",
        )
        assert isinstance(cp_id, int)
        assert cp_id > 0

    def test_get_latest_checkpoint(self, tmp_db: SessionDB):
        wt_id = tmp_db.create_worktree("feature/lc", task_description="latest cp test")
        tmp_db.create_checkpoint(wt_id, git_sha="aaa", label="first")
        tmp_db.create_checkpoint(wt_id, git_sha="bbb", label="second")
        cp_id3 = tmp_db.create_checkpoint(
            wt_id,
            git_sha="ccc",
            test_results={"passed": 5},
            artifact_snapshot=["file.py"],
            graph_delta={"changed_symbols": ["foo"], "impacted_callers": ["bar"]},
            label="third",
        )

        latest = tmp_db.get_latest_checkpoint(wt_id)
        assert latest is not None
        assert latest["id"] == cp_id3
        assert latest["git_sha"] == "ccc"
        assert latest["label"] == "third"
        assert latest["test_results"] == {"passed": 5}
        assert latest["artifact_snapshot"] == ["file.py"]
        assert latest["graph_delta"]["changed_symbols"] == ["foo"]

    def test_get_latest_checkpoint_empty(self, tmp_db: SessionDB):
        wt_id = tmp_db.create_worktree("feature/empty", task_description="no checkpoints")
        assert tmp_db.get_latest_checkpoint(wt_id) is None

    def test_checkpoint_json_round_trip(self, tmp_db: SessionDB):
        wt_id = tmp_db.create_worktree("feature/json", task_description="json test")
        graph = {
            "changed_symbols": ["AuthService.validate", "TokenManager.refresh"],
            "impacted_callers": ["login_handler", "api_middleware"],
            "affected_communities": [1, 3, 7],
            "disrupted_processes": [42],
        }
        cp_id = tmp_db.create_checkpoint(wt_id, graph_delta=graph)
        latest = tmp_db.get_latest_checkpoint(wt_id)
        assert latest["graph_delta"] == graph


class TestCorrectionCycleCRUD:
    def test_create_correction_cycle(self, tmp_db: SessionDB):
        wt_id = tmp_db.create_worktree("feature/cc", task_description="cycle test")
        cp_id = tmp_db.create_checkpoint(wt_id, git_sha="base")
        cc_id = tmp_db.create_correction_cycle(
            wt_id,
            cycle_number=1,
            trigger_error="TypeError: undefined is not a function",
            error_context={"browser_log": "Uncaught TypeError at line 42"},
            checkpoint_id=cp_id,
            agent_session_id="agent-sess-001",
            outcome="passed",
            duration_seconds=120,
        )
        assert isinstance(cc_id, int)
        assert cc_id > 0

    def test_get_correction_cycles(self, tmp_db: SessionDB):
        wt_id = tmp_db.create_worktree("feature/gc", task_description="get cycles test")
        cp_id = tmp_db.create_checkpoint(wt_id, git_sha="base")

        tmp_db.create_correction_cycle(
            wt_id, 1,
            trigger_error="Test failed: auth module",
            checkpoint_id=cp_id,
            outcome="failed",
            duration_seconds=60,
        )
        tmp_db.create_correction_cycle(
            wt_id, 2,
            trigger_error="Test failed: auth module (retry)",
            checkpoint_id=cp_id,
            outcome="passed",
            duration_seconds=45,
        )

        cycles = tmp_db.get_correction_cycles(wt_id)
        assert len(cycles) == 2
        assert cycles[0]["cycle_number"] == 1
        assert cycles[0]["outcome"] == "failed"
        assert cycles[1]["cycle_number"] == 2
        assert cycles[1]["outcome"] == "passed"

    def test_error_context_json_round_trip(self, tmp_db: SessionDB):
        wt_id = tmp_db.create_worktree("feature/ec", task_description="error ctx")
        ctx = {
            "browser_logs": ["Error: CORS", "Warning: Mixed content"],
            "db_errors": [],
            "aws_logs": {"lambda": "timeout after 30s"},
        }
        cc_id = tmp_db.create_correction_cycle(
            wt_id, 1, error_context=ctx, trigger_error="CORS error",
        )
        cycles = tmp_db.get_correction_cycles(wt_id)
        assert len(cycles) == 1
        assert cycles[0]["error_context"] == ctx

    def test_outcome_check_constraint(self, tmp_db: SessionDB):
        wt_id = tmp_db.create_worktree("feature/oc", task_description="constraint")
        with pytest.raises(sqlite3.IntegrityError):
            tmp_db.create_correction_cycle(
                wt_id, 1, outcome="invalid_outcome",
            )


# ---------------------------------------------------------------------------
# FTS tests
# ---------------------------------------------------------------------------


class TestFTSSearch:
    def test_search_worktrees_by_task(self, tmp_db: SessionDB):
        tmp_db.create_worktree(
            "feature/oauth", task_description="Fix OAuth2 token refresh flow",
        )
        tmp_db.create_worktree(
            "feature/stripe", task_description="Implement Stripe payment webhooks",
        )
        tmp_db.create_worktree(
            "feature/deploy", task_description="Fix Docker container startup",
        )

        results = tmp_db.search_worktrees("OAuth token")
        assert len(results) >= 1
        assert any("OAuth" in r["task_description"] for r in results)

    def test_search_worktrees_by_branch(self, tmp_db: SessionDB):
        tmp_db.create_worktree(
            "feature/payment-gateway", task_description="Payment gateway integration",
        )
        results = tmp_db.search_worktrees("payment")
        assert len(results) >= 1

    def test_search_correction_errors(self, tmp_db: SessionDB):
        wt_id = tmp_db.create_worktree("feature/err", task_description="error search")
        tmp_db.create_correction_cycle(
            wt_id, 1,
            trigger_error="CORS policy blocked request to API gateway",
        )
        tmp_db.create_correction_cycle(
            wt_id, 2,
            trigger_error="Database connection timeout after 30 seconds",
        )

        results = tmp_db.search_correction_errors("CORS")
        assert len(results) >= 1
        assert any("CORS" in r["trigger_error"] for r in results)

        results = tmp_db.search_correction_errors("database timeout")
        assert len(results) >= 1

    def test_fts_empty_results(self, tmp_db: SessionDB):
        results = tmp_db.search_worktrees("nonexistent_xyzzy_query_12345")
        assert results == []


# ---------------------------------------------------------------------------
# Migration script tests
# ---------------------------------------------------------------------------


class TestMigrationScript:
    def test_migrate_on_existing_db(self, tmp_path):
        """Migration adds tables to a DB that already has sessions/messages."""
        db_path = tmp_path / "existing.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                filepath TEXT NOT NULL,
                project TEXT,
                message_count INTEGER DEFAULT 0,
                file_size_bytes INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO sessions VALUES ('s1', '/tmp/s1.jsonl', 'proj', 5, 1000, NULL, NULL)"
        )
        conn.commit()
        conn.close()

        from scripts.migrate_loopwright import migrate
        migrate(db_path)

        conn = sqlite3.connect(str(db_path))
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "worktrees" in tables
        assert "checkpoints" in tables
        assert "correction_cycles" in tables
        assert "worktrees_fts" in tables

        row = conn.execute("SELECT * FROM sessions WHERE session_id='s1'").fetchone()
        assert row is not None
        conn.close()

    def test_migrate_idempotent(self, tmp_path):
        """Running migration twice doesn't error or duplicate anything."""
        db_path = tmp_path / "idempotent.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                filepath TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

        from scripts.migrate_loopwright import migrate
        migrate(db_path)
        migrate(db_path)

        conn = sqlite3.connect(str(db_path))
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='worktrees'"
            ).fetchall()
        ]
        assert len(tables) == 1
        conn.close()


# ---------------------------------------------------------------------------
# Integration: full workflow
# ---------------------------------------------------------------------------


class TestFullWorkflow:
    def test_worktree_lifecycle(self, tmp_db: SessionDB):
        """Create worktree -> checkpoints -> correction cycles -> resolve."""
        wt_id = tmp_db.create_worktree(
            "feature/full-flow",
            task_description="End-to-end authentication overhaul",
        )

        cp1 = tmp_db.create_checkpoint(
            wt_id, git_sha="aaa111",
            artifact_snapshot=["src/auth.py"],
            label="initial implementation",
        )

        tmp_db.create_correction_cycle(
            wt_id, 1,
            trigger_error="AssertionError: test_login failed",
            checkpoint_id=cp1,
            outcome="failed",
            duration_seconds=30,
        )

        cp2 = tmp_db.create_checkpoint(
            wt_id, git_sha="bbb222",
            test_results={"passed": 15, "failed": 1},
            artifact_snapshot=["src/auth.py", "tests/test_auth.py"],
            label="after first fix attempt",
        )

        tmp_db.create_correction_cycle(
            wt_id, 2,
            trigger_error="AssertionError: test_token_refresh failed",
            checkpoint_id=cp2,
            outcome="passed",
            duration_seconds=45,
        )

        cp3 = tmp_db.create_checkpoint(
            wt_id, git_sha="ccc333",
            test_results={"passed": 16, "failed": 0},
            artifact_snapshot=["src/auth.py", "src/tokens.py", "tests/test_auth.py"],
            graph_delta={
                "changed_symbols": ["AuthService.login", "TokenManager.refresh"],
                "impacted_callers": ["api_handler"],
                "affected_communities": [2],
                "disrupted_processes": [],
            },
            label="all tests passing",
        )

        tmp_db.update_worktree_status(wt_id, "passed")

        wt = tmp_db.get_worktree(wt_id)
        assert wt["status"] == "passed"
        assert wt["resolved_at"] is not None

        latest = tmp_db.get_latest_checkpoint(wt_id)
        assert latest["git_sha"] == "ccc333"
        assert latest["test_results"]["failed"] == 0

        cycles = tmp_db.get_correction_cycles(wt_id)
        assert len(cycles) == 2
        assert cycles[0]["outcome"] == "failed"
        assert cycles[1]["outcome"] == "passed"

    def test_existing_tables_untouched(self, tmp_db: SessionDB):
        """Verify original sessions/messages tables still work after schema additions."""
        with tmp_db._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, filepath) VALUES (?, ?)",
                ("existing-sess", "/tmp/existing.jsonl"),
            )
            conn.execute(
                """INSERT INTO messages
                   (session_id, sequence, role, content)
                   VALUES (?, ?, ?, ?)""",
                ("existing-sess", 0, "user", "Hello world"),
            )

        results = tmp_db.search("Hello")
        assert len(results) >= 1
        assert results[0]["content"] == "Hello world"


# ---------------------------------------------------------------------------
# Query helper tests
# ---------------------------------------------------------------------------


class TestQueryHelpers:
    def test_get_correction_cycle_count(self, tmp_db: SessionDB):
        wt_id = tmp_db.create_worktree("feature/count", task_description="count test")
        assert tmp_db.get_correction_cycle_count(wt_id) == 0

        tmp_db.create_correction_cycle(wt_id, 1, trigger_error="error 1")
        tmp_db.create_correction_cycle(wt_id, 2, trigger_error="error 2")
        assert tmp_db.get_correction_cycle_count(wt_id) == 2

    def test_get_correction_cycle_count_empty(self, tmp_db: SessionDB):
        wt_id = tmp_db.create_worktree("feature/empty-count", task_description="no cycles")
        assert tmp_db.get_correction_cycle_count(wt_id) == 0

    def test_get_latest_correction_cycle(self, tmp_db: SessionDB):
        wt_id = tmp_db.create_worktree("feature/latest-cc", task_description="latest cycle")
        tmp_db.create_correction_cycle(
            wt_id, 1, trigger_error="first error", outcome="failed",
        )
        tmp_db.create_correction_cycle(
            wt_id, 2,
            trigger_error="second error",
            error_context={"errors": [{"file": "a.ts", "line": 10}]},
            outcome="passed",
        )

        latest = tmp_db.get_latest_correction_cycle(wt_id)
        assert latest is not None
        assert latest["cycle_number"] == 2
        assert latest["trigger_error"] == "second error"
        assert latest["outcome"] == "passed"
        assert isinstance(latest["error_context"], dict)

    def test_get_latest_correction_cycle_none(self, tmp_db: SessionDB):
        wt_id = tmp_db.create_worktree("feature/no-cc", task_description="none")
        assert tmp_db.get_latest_correction_cycle(wt_id) is None

    def test_list_worktrees_by_status(self, tmp_db: SessionDB):
        tmp_db.create_worktree("feature/a", task_description="active one")
        wt_b = tmp_db.create_worktree("feature/b", task_description="will fail")
        tmp_db.create_worktree("feature/c", task_description="active two")
        tmp_db.update_worktree_status(wt_b, "failed")

        active = tmp_db.list_worktrees_by_status("active")
        assert len(active) == 2
        assert all(w["status"] == "active" for w in active)

        failed = tmp_db.list_worktrees_by_status("failed")
        assert len(failed) == 1
        assert failed[0]["id"] == wt_b

    def test_list_worktrees_by_status_empty(self, tmp_db: SessionDB):
        results = tmp_db.list_worktrees_by_status("escalated")
        assert results == []

    def test_list_worktrees_by_status_respects_limit(self, tmp_db: SessionDB):
        for i in range(5):
            tmp_db.create_worktree(f"feature/lim-{i}", task_description=f"task {i}")
        results = tmp_db.list_worktrees_by_status("active", limit=3)
        assert len(results) == 3

    def test_get_worktree_with_cycles(self, tmp_db: SessionDB):
        wt_id = tmp_db.create_worktree(
            "feature/full",
            task_description="full worktree query",
        )
        cp_id = tmp_db.create_checkpoint(
            wt_id, git_sha="abc123",
            test_results={"passed": 5, "failed": 1},
            artifact_snapshot=["src/main.py"],
        )
        tmp_db.create_correction_cycle(
            wt_id, 1,
            trigger_error="test_main failed",
            checkpoint_id=cp_id,
            outcome="failed",
        )
        tmp_db.create_correction_cycle(
            wt_id, 2,
            trigger_error="test_main assertion",
            outcome="passed",
        )

        result = tmp_db.get_worktree_with_cycles(wt_id)
        assert result is not None
        assert result["branch_name"] == "feature/full"
        assert result["task_description"] == "full worktree query"

        assert len(result["correction_cycles"]) == 2
        assert result["correction_cycles"][0]["cycle_number"] == 1
        assert result["correction_cycles"][1]["outcome"] == "passed"

        assert result["latest_checkpoint"] is not None
        assert result["latest_checkpoint"]["git_sha"] == "abc123"
        assert result["latest_checkpoint"]["test_results"] == {"passed": 5, "failed": 1}

    def test_get_worktree_with_cycles_not_found(self, tmp_db: SessionDB):
        assert tmp_db.get_worktree_with_cycles(999) is None

    def test_get_worktree_with_cycles_no_children(self, tmp_db: SessionDB):
        wt_id = tmp_db.create_worktree("feature/bare", task_description="bare wt")
        result = tmp_db.get_worktree_with_cycles(wt_id)
        assert result is not None
        assert result["correction_cycles"] == []
        assert result["latest_checkpoint"] is None


# ---------------------------------------------------------------------------
# Correction brief tests
# ---------------------------------------------------------------------------


class TestCorrectionBrief:
    def test_generate_fresh_worktree(self, tmp_db: SessionDB):
        """Single error, no prior cycles — basic brief generation."""
        from engram.correction_brief import generate_correction_brief

        wt_id = tmp_db.create_worktree(
            "feature/brief-test", task_description="brief generation test",
        )
        brief = generate_correction_brief(
            tmp_db,
            wt_id,
            cycle_number=1,
            trigger_error="TypeError: Cannot read property 'id' of undefined",
            error_context={
                "errors": [
                    {"file": "src/handler.ts", "line": 42, "type": "TypeError",
                     "message": "Cannot read property 'id' of undefined"},
                ],
                "test_command": "bun test",
                "exit_code": 1,
                "changed_files": ["src/handler.ts"],
            },
        )

        assert "# Correction Brief (Cycle 1 of max 3)" in brief
        assert "TypeError" in brief
        assert "src/handler.ts" in brief
        assert "`bun test`" in brief
        assert "## Instructions" in brief

    def test_generate_with_prior_cycles(self, tmp_db: SessionDB):
        """Two prior cycles should populate Prior Attempts section."""
        from engram.correction_brief import generate_correction_brief

        wt_id = tmp_db.create_worktree(
            "feature/prior", task_description="prior cycles test",
        )
        tmp_db.create_checkpoint(wt_id, git_sha="aaa111")
        tmp_db.create_correction_cycle(
            wt_id, 1,
            trigger_error="AssertionError: expected 200 got 401",
            outcome="failed",
            duration_seconds=30,
        )
        tmp_db.create_correction_cycle(
            wt_id, 2,
            trigger_error="AssertionError: missing auth header",
            outcome="failed",
            duration_seconds=45,
        )

        brief = generate_correction_brief(
            tmp_db,
            wt_id,
            cycle_number=3,
            trigger_error="AssertionError: token expired",
        )

        assert "Cycle 3 of max 3" in brief
        assert "## Prior Attempts (This Worktree)" in brief
        assert "Cycle 1:" in brief
        assert "Cycle 2:" in brief
        assert "outcome: **failed**" in brief

    def test_generate_with_checkpoint(self, tmp_db: SessionDB):
        """Checkpoint data should appear in the brief."""
        from engram.correction_brief import generate_correction_brief

        wt_id = tmp_db.create_worktree(
            "feature/cp-brief", task_description="checkpoint brief",
        )
        tmp_db.create_checkpoint(
            wt_id,
            git_sha="deadbeef",
            artifact_snapshot=["src/app.ts", "src/db.ts"],
            label="post-refactor",
        )

        brief = generate_correction_brief(
            tmp_db, wt_id, cycle_number=1,
            trigger_error="ImportError: no module named db",
        )

        assert "## Last Checkpoint" in brief
        assert "`deadbeef`" in brief
        assert "`src/app.ts`" in brief

    def test_generate_with_similar_errors(self, tmp_db: SessionDB):
        """Similar errors from other worktrees should appear."""
        from engram.correction_brief import generate_correction_brief

        other_wt = tmp_db.create_worktree(
            "feature/other", task_description="other worktree",
        )
        tmp_db.create_correction_cycle(
            other_wt, 1,
            trigger_error="CORS policy blocked request to API",
            outcome="passed",
        )

        wt_id = tmp_db.create_worktree(
            "feature/current", task_description="current worktree",
        )
        brief = generate_correction_brief(
            tmp_db, wt_id, cycle_number=1,
            trigger_error="CORS policy blocked request",
        )

        assert "## Similar Errors (Other Worktrees)" in brief
        assert f"Worktree #{other_wt}" in brief


class TestInjectCorrectionBrief:
    def test_creates_claude_md(self, tmp_path):
        from engram.correction_brief import inject_correction_brief

        result = inject_correction_brief(
            tmp_path, "# Test Brief\nSome content\n", cycle_number=1,
        )

        assert result["appended"] is False
        assert result["cycle_number"] == 1

        content = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
        assert "<!-- ENGRAM_CORRECTION_BRIEF:cycle_1 -->" in content
        assert "# Test Brief" in content

    def test_appends_to_existing_claude_md(self, tmp_path):
        from engram.correction_brief import inject_correction_brief

        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Existing Content\nKeep this.\n", encoding="utf-8")

        result = inject_correction_brief(
            tmp_path, "# Correction Brief\nNew stuff\n", cycle_number=2,
        )

        assert result["appended"] is True
        content = claude_md.read_text(encoding="utf-8")
        assert "# Existing Content" in content
        assert "Keep this." in content
        assert "<!-- ENGRAM_CORRECTION_BRIEF:cycle_2 -->" in content
        assert "# Correction Brief" in content

    def test_multiple_injections(self, tmp_path):
        from engram.correction_brief import inject_correction_brief

        inject_correction_brief(tmp_path, "Brief cycle 1", cycle_number=1)
        inject_correction_brief(tmp_path, "Brief cycle 2", cycle_number=2)

        content = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
        assert "<!-- ENGRAM_CORRECTION_BRIEF:cycle_1 -->" in content
        assert "<!-- ENGRAM_CORRECTION_BRIEF:cycle_2 -->" in content
        assert "Brief cycle 1" in content
        assert "Brief cycle 2" in content
