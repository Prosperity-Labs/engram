"""Benchmark: Artifact extraction completeness.

Measures: What % of tool calls in sessions get captured as artifacts?
Target: >80%

Runs against REAL data when ~/.config/engram/sessions.db exists.
Falls back to synthetic data in CI.
"""

import os
import pytest
from engram.recall.artifact_extractor import ArtifactExtractor
from engram.recall.session_db import SessionDB


REAL_DB = os.path.expanduser("~/.config/engram/sessions.db")
HAS_REAL_DATA = os.path.exists(REAL_DB)


@pytest.fixture
def benchmark_db(tmp_db):
    """Synthetic DB with known tool calls for CI."""
    db = tmp_db
    session_id = "benchmark-artifacts-001"
    with db._connect() as conn:
        conn.execute(
            """INSERT INTO sessions
               (session_id, filepath, project, message_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, "/tmp/bench.jsonl", "bench-project",
             20, "2026-02-20T10:00:00Z", "2026-02-20T11:00:00Z"),
        )
        tool_messages = [
            (session_id, 0, "assistant", '{"file_path": "/src/app.ts"}', None, "Read", 100, 50, 0, 0),
            (session_id, 1, "assistant", '{"file_path": "/src/app.ts", "old_string": "a", "new_string": "b"}', None, "Edit", 100, 50, 0, 0),
            (session_id, 2, "assistant", '{"file_path": "/src/new.ts", "content": "hello"}', None, "Write", 100, 50, 0, 0),
            (session_id, 3, "assistant", '{"command": "npm test"}', None, "Bash", 100, 50, 0, 0),
            (session_id, 4, "assistant", '{"pattern": "**/*.ts"}', None, "Glob", 100, 50, 0, 0),
            (session_id, 5, "assistant", '{"pattern": "TODO", "path": "/src"}', None, "Grep", 100, 50, 0, 0),
            (session_id, 6, "assistant", '{"query": "search"}', None, "mcp_noodlbox", 100, 50, 0, 0),
            (session_id, 7, "assistant", "Just thinking about the code...", None, None, 100, 50, 0, 0),
            (session_id, 8, "assistant", "Error: Module not found", None, None, 100, 50, 0, 0),
            (session_id, 9, "assistant", '{"file_path": "/src/db.py"}', None, "Read", 100, 50, 0, 0),
        ]
        conn.executemany(
            """INSERT INTO messages
               (session_id, sequence, role, content, timestamp,
                tool_name, token_usage_in, token_usage_out,
                cache_read_tokens, cache_create_tokens)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            tool_messages,
        )
    return db


EXPECTED_TOOL_CALL_COUNT = 8  # Read, Edit, Write, Bash, Glob, Grep, mcp_noodlbox, Read


def test_artifact_completeness(benchmark_db):
    """Benchmark: artifact extraction captures >80% of tool calls (synthetic)."""
    extractor = ArtifactExtractor(benchmark_db)
    artifacts = extractor.extract_session("benchmark-artifacts-001")

    tool_artifacts = [a for a in artifacts if a["artifact_type"] != "error"]
    error_artifacts = [a for a in artifacts if a["artifact_type"] == "error"]

    completeness = len(tool_artifacts) / EXPECTED_TOOL_CALL_COUNT

    print(f"\n--- Artifact Completeness Benchmark (synthetic) ---")
    print(f"Tool calls expected: {EXPECTED_TOOL_CALL_COUNT}")
    print(f"Tool artifacts found: {len(tool_artifacts)}")
    print(f"Completeness: {completeness:.0%}")
    print(f"Error detection: {len(error_artifacts)} errors found")
    print(f"Target: >80%")
    print(f"Result: {'PASS' if completeness >= 0.80 else 'FAIL'}")

    assert completeness >= 0.80, f"Artifact completeness {completeness:.0%} < 80% target"


def test_artifact_types_correct(benchmark_db):
    """Verify extracted artifacts have correct types."""
    extractor = ArtifactExtractor(benchmark_db)
    artifacts = extractor.extract_session("benchmark-artifacts-001")

    type_map = {a["target"]: a["artifact_type"] for a in artifacts if a["artifact_type"] != "error"}

    assert type_map.get("/src/app.ts") == "file_read" or type_map.get("/src/db.py") == "file_read"
    assert type_map.get("npm test") == "command"
    assert type_map.get("mcp_noodlbox") == "api_call"


@pytest.mark.skipif(not HAS_REAL_DATA, reason="No real session data at ~/.config/engram/sessions.db")
def test_artifact_completeness_real_data():
    """Benchmark against REAL data — the metric that matters.

    Measures: of all messages with tool_name set, how many produced an artifact?
    This is what we tested manually and got 89.1% after the ast.literal_eval fix.
    """
    db = SessionDB(REAL_DB)
    extractor = ArtifactExtractor(db)

    with db._connect() as conn:
        # Count messages that have a tool_name (these should produce artifacts)
        total_tool_messages = conn.execute(
            """SELECT COUNT(*) as cnt FROM messages
               WHERE tool_name IS NOT NULL AND tool_name != ''"""
        ).fetchone()["cnt"]

        # Count artifacts that are NOT errors (tool-derived artifacts)
        total_tool_artifacts = conn.execute(
            "SELECT COUNT(*) as cnt FROM artifacts WHERE artifact_type != 'error'"
        ).fetchone()["cnt"]

        # Breakdown by type
        by_type = conn.execute(
            """SELECT artifact_type, COUNT(*) as cnt
               FROM artifacts
               GROUP BY artifact_type
               ORDER BY cnt DESC"""
        ).fetchall()

        # Unparseable messages (tool_name set but no artifact)
        unparsed = conn.execute(
            """SELECT m.tool_name, COUNT(*) as cnt
               FROM messages m
               LEFT JOIN artifacts a ON a.session_id = m.session_id AND a.sequence = m.sequence
               WHERE m.tool_name IS NOT NULL AND m.tool_name != ''
               AND a.id IS NULL
               GROUP BY m.tool_name
               ORDER BY cnt DESC
               LIMIT 10"""
        ).fetchall()

    completeness = total_tool_artifacts / total_tool_messages if total_tool_messages > 0 else 0

    print(f"\n--- Artifact Completeness Benchmark (REAL DATA) ---")
    print(f"Total tool messages: {total_tool_messages:,}")
    print(f"Artifacts extracted: {total_tool_artifacts:,}")
    print(f"Completeness: {completeness:.1%}")
    print(f"\nBy type:")
    for row in by_type:
        print(f"  {row['artifact_type']:15s} {row['cnt']:>6,}")
    if unparsed:
        print(f"\nUnparsed tool types (top 10):")
        for row in unparsed:
            print(f"  {row['tool_name']:20s} {row['cnt']:>5} messages missed")
    print(f"\nTarget: >80%")
    print(f"Result: {'PASS' if completeness >= 0.80 else 'FAIL'}")

    assert completeness >= 0.80, f"Artifact completeness {completeness:.1%} < 80% target"
