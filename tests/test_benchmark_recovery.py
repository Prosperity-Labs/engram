"""Benchmark: Context recovery from Engram data.

Measures: Can we answer basic project questions from stored session data?
Target: >60%

Runs against REAL data when ~/.config/engram/sessions.db exists.
Falls back to synthetic data in CI.

These are deterministic checks — no LLM needed. We verify that Engram's
stored data (sessions, artifacts, search) contains the information needed
to answer common project questions.
"""

import os
import pytest
from engram.recall.session_db import SessionDB
from engram.recall.artifact_extractor import ArtifactExtractor
from engram.stats import compute_project_stats


REAL_DB = os.path.expanduser("~/.config/engram/sessions.db")
HAS_REAL_DATA = os.path.exists(REAL_DB)


@pytest.fixture
def recovery_db(tmp_db):
    """Synthetic DB for CI."""
    db = tmp_db
    with db._connect() as conn:
        conn.execute(
            """INSERT INTO sessions
               (session_id, filepath, project, message_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("recovery-auth", "/tmp/auth.jsonl", "recovery-project",
             10, "2026-02-18T10:00:00Z", "2026-02-18T11:00:00Z"),
        )
        conn.executemany(
            """INSERT INTO messages
               (session_id, sequence, role, content, timestamp,
                tool_name, token_usage_in, token_usage_out,
                cache_read_tokens, cache_create_tokens)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                ("recovery-auth", 0, "user", "Add JWT authentication to the API", None, None, 1000, 100, 0, 0),
                ("recovery-auth", 1, "assistant", '{"file_path": "/src/auth/middleware.ts"}', None, "Read", 2000, 200, 500, 0),
                ("recovery-auth", 2, "assistant", '{"file_path": "/src/auth/middleware.ts", "old_string": "a", "new_string": "b"}', None, "Edit", 2000, 300, 500, 0),
                ("recovery-auth", 3, "assistant", '{"command": "npm test"}', None, "Bash", 500, 50, 0, 0),
                ("recovery-auth", 4, "assistant", "Error: JWT_SECRET not defined in environment", None, None, 500, 50, 0, 0),
                ("recovery-auth", 5, "assistant", "Fixed by adding JWT_SECRET to .env.example", None, None, 500, 100, 0, 0),
            ],
        )
        conn.execute(
            """INSERT INTO sessions
               (session_id, filepath, project, message_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("recovery-db", "/tmp/db.jsonl", "recovery-project",
             8, "2026-02-19T10:00:00Z", "2026-02-19T11:00:00Z"),
        )
        conn.executemany(
            """INSERT INTO messages
               (session_id, sequence, role, content, timestamp,
                tool_name, token_usage_in, token_usage_out,
                cache_read_tokens, cache_create_tokens)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                ("recovery-db", 0, "user", "Optimize database queries for user profiles", None, None, 1000, 100, 0, 0),
                ("recovery-db", 1, "assistant", '{"file_path": "/src/db/queries.ts"}', None, "Read", 2000, 200, 0, 0),
                ("recovery-db", 2, "assistant", '{"file_path": "/src/db/queries.ts", "old_string": "c", "new_string": "d"}', None, "Edit", 2000, 200, 0, 0),
            ],
        )
    extractor = ArtifactExtractor(db)
    extractor.extract_session("recovery-auth")
    extractor.extract_session("recovery-db")
    return db


def _run_recovery_checks(db, project):
    """Run recovery checks against any DB + project. Returns (passed, total, details)."""
    checks = [
        ("Session count recoverable", lambda: _session_count(db, project) > 0),
        ("Modified files tracked", lambda: _has_artifacts(db, project, "file_write")),
        ("Errors captured", lambda: _has_artifacts(db, project, "error")),
        ("Tool usage stats available", lambda: _has_tool_stats(db, project)),
        ("Topic search works", lambda: _search_finds_something(db, project)),
        ("File read history exists", lambda: _has_artifacts(db, project, "file_read")),
        ("Commands tracked", lambda: _has_artifacts(db, project, "command")),
    ]

    passed = 0
    details = []
    for desc, check_fn in checks:
        try:
            result = check_fn()
            if result:
                passed += 1
            details.append((desc, "PASS" if result else "FAIL"))
        except Exception as e:
            details.append((desc, f"ERROR: {e}"))

    return passed, len(checks), details


def _session_count(db, project):
    with db._connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) as cnt FROM sessions WHERE project = ?",
            (project,),
        ).fetchone()["cnt"]


def _has_artifacts(db, project, artifact_type):
    with db._connect() as conn:
        cnt = conn.execute(
            """SELECT COUNT(*) as cnt FROM artifacts a
               JOIN sessions s ON s.session_id = a.session_id
               WHERE s.project = ? AND a.artifact_type = ?""",
            (project, artifact_type),
        ).fetchone()["cnt"]
    return cnt > 0


def _has_tool_stats(db, project):
    stats = compute_project_stats(db)
    project_stats = [s for s in stats if s["project"] == project]
    return len(project_stats) > 0 and project_stats[0]["tool_calls"] > 0


def _search_finds_something(db, project):
    """Try a few generic searches and see if we get results for this project."""
    with db._connect() as conn:
        # Get a sample word from the project's messages
        row = conn.execute(
            """SELECT content FROM messages m
               JOIN sessions s ON s.session_id = m.session_id
               WHERE s.project = ? AND m.role = 'user' AND m.content IS NOT NULL
               LIMIT 1""",
            (project,),
        ).fetchone()
    if not row or not row["content"]:
        return False
    # Search for the first substantive word
    words = [w for w in row["content"].split() if len(w) > 3]
    if not words:
        return False
    results = db.search(f'"{words[0]}"', limit=5)
    return len(results) > 0


def test_context_recovery(recovery_db):
    """Benchmark: Engram data can answer >60% of project questions (synthetic)."""
    passed, total, details = _run_recovery_checks(recovery_db, "recovery-project")
    recovery_rate = passed / total if total > 0 else 0

    print(f"\n--- Context Recovery Benchmark (synthetic) ---")
    for desc, status in details:
        print(f"  {desc}: {status}")
    print(f"\nRecovery rate: {recovery_rate:.0%} ({passed}/{total})")
    print(f"Target: >60%")
    print(f"Result: {'PASS' if recovery_rate >= 0.60 else 'FAIL'}")

    assert recovery_rate >= 0.60, f"Context recovery {recovery_rate:.0%} < 60% target"


@pytest.mark.skipif(not HAS_REAL_DATA, reason="No real session data at ~/.config/engram/sessions.db")
def test_context_recovery_real_data():
    """Benchmark against REAL session data — tests every project with >50 artifacts."""
    db = SessionDB(REAL_DB)

    with db._connect() as conn:
        projects = conn.execute(
            """SELECT s.project, COUNT(*) as cnt
               FROM artifacts a
               JOIN sessions s ON s.session_id = a.session_id
               WHERE s.project IS NOT NULL
               GROUP BY s.project
               HAVING cnt > 50
               ORDER BY cnt DESC
               LIMIT 5""",
        ).fetchall()

    assert projects, "No projects with sufficient artifacts"

    print(f"\n--- Context Recovery Benchmark (REAL DATA) ---")

    total_passed = 0
    total_checks = 0

    for proj_row in projects:
        project = proj_row["project"]
        passed, total, details = _run_recovery_checks(db, project)
        total_passed += passed
        total_checks += total
        rate = passed / total if total > 0 else 0
        print(f"\n  Project: {project} — {rate:.0%} ({passed}/{total})")
        for desc, status in details:
            print(f"    {desc}: {status}")

    overall = total_passed / total_checks if total_checks > 0 else 0
    print(f"\nOverall recovery: {overall:.0%} ({total_passed}/{total_checks})")
    print(f"Target: >60%")
    print(f"Result: {'PASS' if overall >= 0.60 else 'FAIL'}")

    assert overall >= 0.60, f"Context recovery {overall:.0%} < 60% target"
