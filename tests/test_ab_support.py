from __future__ import annotations

from pathlib import Path

import pytest

from engram.ab_brief import generate_ab_briefs, write_brief_to_worktree
from engram.ab_results import capture_worktree_result, compare_results
from engram.recall.artifact_extractor import ArtifactExtractor


@pytest.fixture
def ab_db(tmp_db):
    db = tmp_db

    # Seed searchable history
    with db._connect() as conn:
        conn.execute(
            """INSERT INTO sessions
               (session_id, filepath, project, message_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "sess-oauth-001",
                "/tmp/sess-oauth-001.jsonl",
                "engram",
                3,
                "2026-02-24T10:00:00Z",
                "2026-02-24T10:05:00Z",
            ),
        )
        conn.execute(
            """INSERT INTO messages
               (session_id, sequence, role, content, timestamp, tool_name)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "sess-oauth-001",
                0,
                "assistant",
                "We previously fixed OAuth token refresh and hit a timeout error in retries.",
                "2026-02-24T10:01:00Z",
                "Edit",
            ),
        )

    wt_hist = db.create_worktree(
        "feature/oauth-refresh",
        session_id="sess-oauth-001",
        task_description="Fix OAuth token refresh flow",
    )
    cp_hist = db.create_checkpoint(
        wt_hist,
        git_sha="hist123",
        artifact_snapshot=["src/auth.py", "tests/test_auth.py"],
        ab_variant_label="A",
        label="oauth refresh attempt",
    )
    db.create_correction_cycle(
        wt_hist,
        1,
        trigger_error="OAuth token refresh timeout during retry",
        checkpoint_id=cp_hist,
        outcome="failed",
    )

    ArtifactExtractor(db)  # ensure artifacts table exists
    with db._connect() as conn:
        conn.execute(
            """INSERT INTO artifacts
               (session_id, artifact_type, target, tool_name, sequence, context)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("sess-oauth-001", "file_write", "src/auth.py", "Edit", 1, None),
        )
        conn.execute(
            """INSERT INTO artifacts
               (session_id, artifact_type, target, tool_name, sequence, context)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("sess-oauth-001", "error", "OAuthError: timeout", None, 2, None),
        )

    return db


class TestABBriefs:
    def test_generates_history_and_cold_variants(self, ab_db):
        briefs = generate_ab_briefs(
            "Fix OAuth token refresh timeout bug",
            session_db_path=ab_db.db_path,
        )

        assert set(briefs) == {"variant_a", "variant_b"}
        assert briefs["variant_a"]["variant_label"] == "A"
        assert briefs["variant_b"]["variant_label"] == "B"
        assert briefs["variant_a"]["content"] != briefs["variant_b"]["content"]
        assert "Prior Context (Engram)" in briefs["variant_a"]["content"]
        assert "cold-start" in briefs["variant_b"]["content"]

    def test_write_brief_to_worktree_updates_claude_and_db(self, ab_db, tmp_path, monkeypatch):
        wt_id = ab_db.create_worktree("feature/ab-a", task_description="A/B write test")
        monkeypatch.setenv("LOOPWRIGHT_WORKTREE_ID", str(wt_id))
        monkeypatch.setenv("LOOPWRIGHT_SESSION_DB_PATH", str(ab_db.db_path))

        out = write_brief_to_worktree(tmp_path, "Variant A brief body", "A")
        claude_md = Path(out["claude_md"])
        assert claude_md.exists()
        assert "Variant A brief body" in claude_md.read_text()

        wt = ab_db.get_worktree(wt_id)
        assert wt["ab_variant_label"] == "A"
        assert wt["ab_brief_metadata"]["variant_label"] == "A"


class TestABResults:
    def test_capture_and_compare_results(self, ab_db):
        # Worktree A
        wt_a = ab_db.create_worktree(
            "feature/ab-a",
            session_id="sess-oauth-001",
            task_description="A variant",
        )
        ab_db.update_worktree_ab_metadata(wt_a, variant_label="A")
        cp_a = ab_db.create_checkpoint(
            wt_a,
            git_sha="a1",
            artifact_snapshot=["src/a.py"],
            ab_variant_label="A",
            label="A commit",
        )
        ab_db.create_correction_cycle(
            wt_a,
            1,
            trigger_error="AssertionError: failed",
            checkpoint_id=cp_a,
            outcome="failed",
        )

        # Worktree B with fewer errors but more files
        wt_b = ab_db.create_worktree(
            "feature/ab-b",
            session_id="sess-oauth-001",
            task_description="B variant",
        )
        ab_db.update_worktree_ab_metadata(wt_b, variant_label="B")
        ab_db.create_checkpoint(
            wt_b,
            git_sha="b1",
            artifact_snapshot=["src/a.py", "src/b.py", "tests/test_b.py"],
            ab_variant_label="B",
            label="B commit",
        )

        result_a = capture_worktree_result(wt_a, ab_db.db_path)
        result_b = capture_worktree_result(wt_b, ab_db.db_path)

        assert result_a["variant_label"] == "A"
        assert result_b["variant_label"] == "B"
        assert ab_db.get_worktree(wt_a)["results_json"]["worktree_id"] == wt_a

        comparison = compare_results(wt_a, wt_b, ab_db.db_path)
        assert comparison["comparison"]["fewer_errors"] == "B"
        assert comparison["comparison"]["more_files_touched"] == "B"
        assert "duration_seconds" in comparison["comparison"]["delta_pct_b_vs_a"]

    def test_full_ab_flow(self, ab_db, tmp_path, monkeypatch):
        task = "Fix OAuth token refresh timeout bug"
        briefs = generate_ab_briefs(task, session_db_path=ab_db.db_path)

        wt_a = ab_db.create_worktree("feature/full-a", task_description=task)
        wt_b = ab_db.create_worktree("feature/full-b", task_description=task)

        monkeypatch.setenv("LOOPWRIGHT_SESSION_DB_PATH", str(ab_db.db_path))

        monkeypatch.setenv("LOOPWRIGHT_WORKTREE_ID", str(wt_a))
        write_brief_to_worktree(tmp_path / "a", briefs["variant_a"]["content"], "A")
        monkeypatch.setenv("LOOPWRIGHT_WORKTREE_ID", str(wt_b))
        write_brief_to_worktree(tmp_path / "b", briefs["variant_b"]["content"], "B")

        ab_db.create_checkpoint(
            wt_a,
            git_sha="aaa111",
            artifact_snapshot=["src/auth.py"],
            ab_variant_label="A",
            label="A checkpoint",
        )
        ab_db.create_correction_cycle(
            wt_a, 1, trigger_error="timeout", outcome="failed"
        )
        ab_db.update_worktree_status(wt_a, "failed")

        ab_db.create_checkpoint(
            wt_b,
            git_sha="bbb222",
            artifact_snapshot=["src/auth.py", "tests/test_auth.py"],
            ab_variant_label="B",
            label="B checkpoint",
        )
        ab_db.update_worktree_status(wt_b, "passed")

        ra = capture_worktree_result(wt_a, ab_db.db_path)
        rb = capture_worktree_result(wt_b, ab_db.db_path)
        cmp = compare_results(wt_a, wt_b, ab_db.db_path)

        assert ra["variant_label"] == "A"
        assert rb["variant_label"] == "B"
        assert cmp["worktree_a"]["results"]["worktree_id"] == wt_a
        assert cmp["worktree_b"]["results"]["worktree_id"] == wt_b
