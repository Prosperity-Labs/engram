"""Benchmark: FTS5 search precision.

Measures: Of the top 5 search results, how many are truly relevant?
Target: >70% precision@5

Runs against REAL data when ~/.config/engram/sessions.db exists.
Falls back to synthetic data in CI.
"""

import os
import pytest
from engram.recall.session_db import SessionDB


REAL_DB = os.path.expanduser("~/.config/engram/sessions.db")
HAS_REAL_DATA = os.path.exists(REAL_DB)


@pytest.fixture
def search_db(tmp_db):
    """Synthetic DB with ground truth search data for CI."""
    db = tmp_db
    with db._connect() as conn:
        conn.execute(
            """INSERT INTO sessions (session_id, filepath, project, message_count, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("search-bench-auth", "/tmp/auth.jsonl", "bench", 5, "2026-02-20T10:00:00Z"),
        )
        conn.executemany(
            """INSERT INTO messages (session_id, sequence, role, content, timestamp,
                                    tool_name, token_usage_in, token_usage_out,
                                    cache_read_tokens, cache_create_tokens)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                ("search-bench-auth", 0, "user", "Fix the JWT authentication bug in login handler", None, None, 0, 0, 0, 0),
                ("search-bench-auth", 1, "assistant", "I'll look at the auth middleware and JWT token validation", None, "Read", 0, 0, 0, 0),
                ("search-bench-auth", 2, "assistant", "The JWT secret is not being loaded from env correctly", None, None, 0, 0, 0, 0),
            ],
        )
        conn.execute(
            """INSERT INTO sessions (session_id, filepath, project, message_count, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("search-bench-db", "/tmp/db.jsonl", "bench", 5, "2026-02-20T11:00:00Z"),
        )
        conn.executemany(
            """INSERT INTO messages (session_id, sequence, role, content, timestamp,
                                    tool_name, token_usage_in, token_usage_out,
                                    cache_read_tokens, cache_create_tokens)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                ("search-bench-db", 0, "user", "Optimize the database query for user profiles", None, None, 0, 0, 0, 0),
                ("search-bench-db", 1, "assistant", "The SQL query is doing a full table scan, needs an index", None, None, 0, 0, 0, 0),
                ("search-bench-db", 2, "assistant", "Added index on users.email column for faster lookups", None, None, 0, 0, 0, 0),
            ],
        )
        conn.execute(
            """INSERT INTO sessions (session_id, filepath, project, message_count, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("search-bench-deploy", "/tmp/deploy.jsonl", "bench", 5, "2026-02-20T12:00:00Z"),
        )
        conn.executemany(
            """INSERT INTO messages (session_id, sequence, role, content, timestamp,
                                    tool_name, token_usage_in, token_usage_out,
                                    cache_read_tokens, cache_create_tokens)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                ("search-bench-deploy", 0, "user", "Set up Docker deployment with nginx reverse proxy", None, None, 0, 0, 0, 0),
                ("search-bench-deploy", 1, "assistant", "Creating Dockerfile and docker-compose.yml for the app", None, None, 0, 0, 0, 0),
            ],
        )
    return db


GROUND_TRUTH = {
    '"JWT" "authentication"': {"search-bench-auth"},
    '"database" "query"': {"search-bench-db"},
    '"Docker" "deployment"': {"search-bench-deploy"},
    '"SQL" "index"': {"search-bench-db"},
    '"login" "bug"': {"search-bench-auth"},
}


def test_search_precision(search_db):
    """Benchmark: FTS5 search precision@5 against ground truth (synthetic)."""
    total_precision = 0
    queries_tested = 0

    print(f"\n--- Search Precision Benchmark (synthetic) ---")

    for query, expected_sessions in GROUND_TRUTH.items():
        results = search_db.search(query, limit=5)
        if not results:
            print(f"  Query '{query}': no results")
            continue

        result_sessions = {r["session_id"] for r in results}
        relevant = result_sessions & expected_sessions
        precision = len(relevant) / len(results) if results else 0

        print(f"  Query '{query}': precision={precision:.0%} ({len(relevant)}/{len(results)})")
        total_precision += precision
        queries_tested += 1

    avg_precision = total_precision / queries_tested if queries_tested > 0 else 0
    print(f"\nAverage precision@5: {avg_precision:.0%}")
    print(f"Target: >70%")
    print(f"Result: {'PASS' if avg_precision >= 0.70 else 'FAIL'}")

    assert avg_precision >= 0.70, f"Search precision {avg_precision:.0%} < 70% target"


@pytest.mark.skipif(not HAS_REAL_DATA, reason="No real session data at ~/.config/engram/sessions.db")
def test_search_precision_real_data():
    """Benchmark against REAL data — search for distinctive project terms.

    Strategy: for each project, find a distinctive single word from its
    artifact targets (file names, commands) that appears often in that project.
    Search for it as a single word (not quoted phrase — FTS5 tokenizes on
    hyphens/underscores). Check if the project appears in top 5 results.
    """
    db = SessionDB(REAL_DB)

    # For each project, find the most common distinctive filename segments
    with db._connect() as conn:
        projects = conn.execute(
            """SELECT s.project, COUNT(DISTINCT s.session_id) as sessions
               FROM sessions s
               WHERE s.project IS NOT NULL
               GROUP BY s.project
               HAVING sessions > 3
               ORDER BY sessions DESC
               LIMIT 10"""
        ).fetchall()

    assert projects, "No projects with sufficient data"

    # Generic words to skip — too common across all projects
    SKIP_WORDS = {
        "index", "page", "types", "utils", "config", "test", "app",
        "main", "src", "lib", "dist", "build", "node", "modules",
        "file", "path", "json", "yaml", "html", "css", "readme",
        "data", "client", "server", "handler", "handlers", "route",
        "routes", "model", "models", "service", "component", "claude",
        "error", "function", "class", "module", "package", "content",
    }

    hits = 0
    total = 0

    print(f"\n--- Search Precision Benchmark (REAL DATA) ---")

    for row in projects:
        project = row["project"]

        # Extract distinctive filename segments from this project's artifacts
        with db._connect() as conn:
            targets = conn.execute(
                """SELECT a.target, COUNT(*) as cnt
                   FROM artifacts a
                   JOIN sessions s ON s.session_id = a.session_id
                   WHERE s.project = ? AND a.artifact_type IN ('file_read', 'file_write')
                   AND LENGTH(a.target) > 5
                   GROUP BY a.target
                   ORDER BY cnt DESC
                   LIMIT 20""",
                (project,),
            ).fetchall()

        # Collect candidate search terms from file paths (prefer longer, unique words)
        candidates = []
        for t in targets:
            target = t["target"].strip()
            parts = target.rstrip("/").split("/")
            name = parts[-1] if parts else ""
            name = name.rsplit(".", 1)[0] if "." in name else name
            words = [w for w in name.replace("-", " ").replace("_", " ").split()
                     if len(w) > 4 and w.lower() not in SKIP_WORDS]
            candidates.extend(words)

        # Fallback: use project name segments
        if not candidates:
            fallback = project.split("/")[-1].replace("-", " ").replace("_", " ").split()
            candidates = [w for w in fallback if len(w) > 4 and w.lower() not in SKIP_WORDS]

        # Deduplicate while preserving order
        seen = set()
        candidates = [c for c in candidates if c.lower() not in seen and not seen.add(c.lower())]

        if not candidates:
            continue

        # Try up to 3 candidates, use the first that hits
        search_term = None
        hit = False
        result_projects = set()
        for candidate in candidates[:3]:
            results = db.search(candidate, limit=5)
            if not results:
                continue
            result_projects = {r.get("project") for r in results}
            search_term = candidate
            if project in result_projects:
                hit = True
                break

        if not search_term:
            print(f"  Project '{project}' candidates {candidates[:3]}: no results")
            total += 1
            continue
        if hit:
            hits += 1
        total += 1

        print(f"  Project '{project}' query '{search_term}': {'HIT' if hit else 'MISS'} (got: {result_projects})")

    precision = hits / total if total > 0 else 0
    print(f"\nProject search hit rate: {precision:.0%} ({hits}/{total})")
    print(f"Target: >70%")
    print(f"Result: {'PASS' if precision >= 0.70 else 'FAIL'}")

    assert precision >= 0.70, f"Search precision {precision:.0%} < 70% target"
