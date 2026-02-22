"""Benchmark: Token savings from brief.

Measures: What % of file_read artifacts are redundant re-reads within the same session?
These are reads the brief would preempt by telling the agent "you already know this file."

Runs against REAL data when ~/.config/engram/sessions.db exists.
Falls back to synthetic data in CI.

Target: >50% of re-reads would be preempted by brief's key files list.
"""

import os
import pytest
from engram.recall.session_db import SessionDB
from engram.recall.artifact_extractor import ArtifactExtractor
from engram.brief import _key_files


REAL_DB = os.path.expanduser("~/.config/engram/sessions.db")
HAS_REAL_DATA = os.path.exists(REAL_DB)


@pytest.fixture
def token_bench_db(tmp_db):
    """Synthetic DB for CI — 3 sessions with overlapping file reads."""
    db = tmp_db
    for i in range(3):
        session_id = f"token-bench-{i:03d}"
        with db._connect() as conn:
            conn.execute(
                """INSERT INTO sessions
                   (session_id, filepath, project, message_count, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, f"/tmp/{session_id}.jsonl", "token-project",
                 20, f"2026-02-{18+i}T10:00:00Z", f"2026-02-{18+i}T11:00:00Z"),
            )
            messages = []
            for j in range(20):
                if j < 10:
                    tool = "Read"
                    path = ["/src/app.ts", "/src/db.py", "/src/config.ts",
                            "/src/auth.ts", "/src/types.ts"][j % 5]
                    content = f'{{"file_path": "{path}"}}'
                else:
                    tool = "Edit" if j % 2 == 0 else None
                    content = f'{{"file_path": "/src/app.ts"}}' if tool else "Working..."
                messages.append(
                    (session_id, j, "assistant", content, None, tool, 1000, 100, 0, 0)
                )
            conn.executemany(
                """INSERT INTO messages
                   (session_id, sequence, role, content, timestamp,
                    tool_name, token_usage_in, token_usage_out,
                    cache_read_tokens, cache_create_tokens)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                messages,
            )
    extractor = ArtifactExtractor(db)
    for i in range(3):
        extractor.extract_session(f"token-bench-{i:03d}")
    return db


def _measure_reread_waste(db, project):
    """Core metric: what % of file reads are redundant re-reads within the same session?"""
    with db._connect() as conn:
        # Total file reads for this project
        total_reads = conn.execute(
            """SELECT COUNT(*) as cnt FROM artifacts a
               JOIN sessions s ON s.session_id = a.session_id
               WHERE s.project = ? AND a.artifact_type = 'file_read'""",
            (project,),
        ).fetchone()["cnt"]

        # Redundant re-reads: same file read multiple times in same session
        redundant = conn.execute(
            """SELECT SUM(times_read - 1) as wasted FROM (
                   SELECT COUNT(*) as times_read
                   FROM artifacts a
                   JOIN sessions s ON s.session_id = a.session_id
                   WHERE s.project = ? AND a.artifact_type = 'file_read'
                   GROUP BY a.session_id, a.target
                   HAVING times_read > 1
               )""",
            (project,),
        ).fetchone()["wasted"] or 0

    return total_reads, redundant


def _measure_brief_preemption(db, project):
    """What % of re-reads would the brief's key files list preempt?"""
    key_files_data = _key_files(db, project)
    brief_files = set()
    for f in key_files_data["most_read"]:
        brief_files.add(f["path"])
    for f in key_files_data["most_modified"]:
        brief_files.add(f["path"])

    with db._connect() as conn:
        # Get all re-read files (read > 1 time in same session)
        rereads = conn.execute(
            """SELECT a.target, COUNT(*) - 1 as redundant_count
               FROM artifacts a
               JOIN sessions s ON s.session_id = a.session_id
               WHERE s.project = ? AND a.artifact_type = 'file_read'
               GROUP BY a.session_id, a.target
               HAVING COUNT(*) > 1""",
            (project,),
        ).fetchall()

    total_redundant = 0
    preempted = 0
    for row in rereads:
        total_redundant += row["redundant_count"]
        if row["target"] in brief_files:
            preempted += row["redundant_count"]

    return total_redundant, preempted, brief_files


def test_token_savings(token_bench_db):
    """Benchmark: brief preempts >50% of redundant file re-reads."""
    db = token_bench_db
    project = "token-project"

    total_reads, redundant = _measure_reread_waste(db, project)
    total_redundant, preempted, brief_files = _measure_brief_preemption(db, project)

    savings = preempted / total_redundant if total_redundant > 0 else 0

    print(f"\n--- Token Savings Benchmark (synthetic) ---")
    print(f"Total reads: {total_reads}")
    print(f"Redundant re-reads: {redundant} ({redundant/total_reads*100:.0f}%)" if total_reads else "N/A")
    print(f"Brief would preempt: {preempted}/{total_redundant} = {savings:.0%}")
    print(f"Brief files: {len(brief_files)}")
    print(f"Target: >50%")
    print(f"Result: {'PASS' if savings >= 0.50 else 'FAIL'}")

    assert savings >= 0.50, f"Token savings {savings:.0%} < 50% target"


@pytest.mark.skipif(not HAS_REAL_DATA, reason="No real session data at ~/.config/engram/sessions.db")
def test_token_savings_real_data():
    """Benchmark against REAL session data — the actual metric that matters."""
    db = SessionDB(REAL_DB)

    # Find the project with the most artifacts
    with db._connect() as conn:
        top_project = conn.execute(
            """SELECT s.project, COUNT(*) as cnt
               FROM artifacts a
               JOIN sessions s ON s.session_id = a.session_id
               WHERE s.project IS NOT NULL
               GROUP BY s.project
               ORDER BY cnt DESC
               LIMIT 1""",
        ).fetchone()

    assert top_project, "No projects with artifacts found"
    project = top_project["project"]

    total_reads, redundant = _measure_reread_waste(db, project)
    total_redundant, preempted, brief_files = _measure_brief_preemption(db, project)

    reread_pct = redundant / total_reads * 100 if total_reads else 0
    savings = preempted / total_redundant if total_redundant > 0 else 0

    print(f"\n--- Token Savings Benchmark (REAL DATA: {project}) ---")
    print(f"Total reads: {total_reads}")
    print(f"Redundant re-reads: {redundant} ({reread_pct:.1f}% of all reads)")
    print(f"Brief would preempt: {preempted}/{total_redundant} = {savings:.0%}")
    print(f"Brief key files: {len(brief_files)}")
    print(f"Target: >50%")
    print(f"Result: {'PASS' if savings >= 0.50 else 'FAIL'}")

    # Also run across ALL projects
    with db._connect() as conn:
        all_total = conn.execute(
            "SELECT COUNT(*) as cnt FROM artifacts WHERE artifact_type = 'file_read'"
        ).fetchone()["cnt"]
        all_redundant = conn.execute(
            """SELECT SUM(times_read - 1) as wasted FROM (
                   SELECT COUNT(*) as times_read
                   FROM artifacts WHERE artifact_type = 'file_read'
                   GROUP BY session_id, target
                   HAVING times_read > 1
               )"""
        ).fetchone()["wasted"] or 0

    global_reread_pct = all_redundant / all_total * 100 if all_total else 0
    print(f"\nGlobal stats: {all_redundant}/{all_total} reads redundant ({global_reread_pct:.1f}%)")

    assert savings >= 0.50, f"Token savings {savings:.0%} < 50% target"
