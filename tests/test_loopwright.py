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
