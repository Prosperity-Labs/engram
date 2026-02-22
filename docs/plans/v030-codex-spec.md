# Agent Spec: Codex — Brief Generator + Benchmark Tests

> **Branch:** `feat/brief-and-benchmarks`
> **Agent:** Codex
> **Scope:** `engram/brief.py` (new) + `tests/test_brief.py` (new) + `tests/test_benchmark_artifacts.py` (new) + `tests/test_benchmark_search.py` (new)

---

## Context

Engram v0.2.0 is shipped with 70 tests and 11 CLI commands. The database has:
- `sessions` table: session_id, filepath, project, message_count, file_size_bytes, created_at, updated_at
- `messages` table: id, session_id, sequence, role, content, timestamp, tool_name, token_usage_in, token_usage_out, cache_read_tokens, cache_create_tokens
- `messages_fts` FTS5 virtual table for full-text search
- `artifacts` table: id, session_id, artifact_type, target, tool_name, sequence, context

Artifact types: `file_read`, `file_write`, `file_create`, `command`, `api_call`, `error`

The `compute_project_stats()` function in `engram/stats.py` already computes per-project exploration/mutation/execution ratios. Reuse it.

---

## Task 1: Brief Generator

**New file:** `engram/brief.py`

### Interface contract:

```python
from __future__ import annotations

import json
from collections import Counter
from engram.recall.session_db import SessionDB
from engram.stats import compute_project_stats


def _project_overview(db: SessionDB, project: str) -> dict:
    """Gather high-level project metrics.

    Returns:
    {
        "sessions": int,
        "messages": int,
        "tokens_in": int,
        "tokens_out": int,
        "cost_estimate": float,
        "first_session": str | None,   # ISO date
        "last_session": str | None,    # ISO date
    }
    """


def _key_files(db: SessionDB, project: str) -> dict:
    """Find most-accessed and most-modified files from artifacts table.

    Returns:
    {
        "most_read": list[dict],      # [{"path": str, "count": int, "sessions": int}, ...]
        "most_modified": list[dict],  # [{"path": str, "count": int, "sessions": int}, ...]
    }
    """


def _architecture_patterns(db: SessionDB, project: str) -> list[dict]:
    """Search for architecture decisions in session content.

    Returns list of dicts:
    [
        {
            "snippet": str,       # first 200 chars of matching content
            "timestamp": str,
            "session_id": str,
        },
        ...
    ]
    Max 10 results.
    """


def _common_errors(db: SessionDB, project: str) -> list[dict]:
    """Find recurring errors from artifacts table.

    Returns list of dicts:
    [
        {
            "error_text": str,      # first 100 chars of error target
            "occurrences": int,     # total count
            "sessions": int,        # distinct session count
        },
        ...
    ]
    Grouped by error text prefix. Max 10 results.
    """


def _cost_profile(db: SessionDB, project: str) -> dict:
    """Reuse compute_project_stats to get cost breakdown.

    Returns:
    {
        "exploration_pct": int,
        "mutation_pct": int,
        "execution_pct": int,
        "recommendation": str | None,   # e.g. "Consider code index MCP if exploration >30%"
    }
    """


def generate_brief(
    db: SessionDB,
    project: str,
    format: str = "markdown",  # "markdown" or "json"
) -> str:
    """Orchestrate all data-gathering functions and produce the brief.

    Calls all 5 functions above, assembles into either markdown or JSON.
    Target: 500-2000 tokens of output.

    Returns: formatted string (markdown or JSON)
    """
```

### SQL queries:

**`_project_overview`:**

```sql
SELECT COUNT(DISTINCT s.session_id) as sessions,
       SUM(s.message_count) as messages,
       COALESCE(SUM(m.token_usage_in), 0) as tokens_in,
       COALESCE(SUM(m.token_usage_out), 0) as tokens_out,
       MIN(s.created_at) as first_session,
       MAX(s.updated_at) as last_session
FROM sessions s
LEFT JOIN messages m ON m.session_id = s.session_id
WHERE s.project = ?
```

Cost estimate uses Opus pricing (same as `session_db.py`):
```python
_COST_PER_M = {
    "input": 15.0,
    "output": 75.0,
    "cache_read": 1.50,
    "cache_create": 18.75,
}
cost = (tokens_in * 15.0 + tokens_out * 75.0) / 1_000_000
```

**`_key_files` — most read:**

```sql
SELECT a.target as path,
       COUNT(*) as count,
       COUNT(DISTINCT a.session_id) as sessions
FROM artifacts a
JOIN sessions s ON s.session_id = a.session_id
WHERE s.project = ?
  AND a.artifact_type = 'file_read'
  AND a.target NOT LIKE '%*%'
GROUP BY a.target
ORDER BY count DESC
LIMIT 10
```

**`_key_files` — most modified:**

```sql
SELECT a.target as path,
       COUNT(*) as count,
       COUNT(DISTINCT a.session_id) as sessions
FROM artifacts a
JOIN sessions s ON s.session_id = a.session_id
WHERE s.project = ?
  AND a.artifact_type IN ('file_write', 'file_create')
GROUP BY a.target
ORDER BY count DESC
LIMIT 10
```

**`_architecture_patterns`:**

Use `db.search()` with decision-related keywords scoped to the project. The search method already supports FTS5.

```python
DECISION_KEYWORDS = ["chose", "decided", "because", "instead of", "trade-off",
                     "architecture", "pattern", "approach", "design"]
```

For each keyword, search with `db.search(keyword, limit=3, session_id=None)` and filter results where `result["project"] == project`. Deduplicate by content prefix. Return top 10 by rank.

**Important:** The `db.search()` method returns dicts with keys: `session_id`, `project`, `role`, `tool_name`, `snippet`, `content`, `timestamp`, `rank`.

**`_common_errors`:**

```sql
SELECT SUBSTR(a.target, 1, 100) as error_text,
       COUNT(*) as occurrences,
       COUNT(DISTINCT a.session_id) as sessions
FROM artifacts a
JOIN sessions s ON s.session_id = a.session_id
WHERE s.project = ?
  AND a.artifact_type = 'error'
GROUP BY SUBSTR(a.target, 1, 100)
ORDER BY occurrences DESC
LIMIT 10
```

**`_cost_profile`:**

Reuse the existing `compute_project_stats(db)` from `engram/stats.py`. Filter the result list for the matching project. Extract exploration_ratio, mutation_ratio, execution_ratio and convert to percentages.

```python
from engram.stats import compute_project_stats

all_stats = compute_project_stats(db)
project_stats = next((s for s in all_stats if s["project"] == project), None)
if project_stats is None:
    return {"exploration_pct": 0, "mutation_pct": 0, "execution_pct": 0, "recommendation": None}

exploration_pct = int(project_stats["exploration_ratio"] * 100)
recommendation = None
if exploration_pct > 30:
    recommendation = "High exploration ratio — consider adding a code index MCP server to reduce file discovery cost."
```

### Markdown output format:

```markdown
# Project Brief: {project}
> Auto-generated by Engram from {sessions} sessions ({first_session} to {last_session})

## Overview
- **Sessions:** {sessions} | **Messages:** {messages} | **Est. Cost:** ${cost:.2f}

## Key Files
### Most Modified
- `{path}` ({count} edits across {sessions} sessions)
...

### Most Read
- `{path}` ({count} reads across {sessions} sessions)
...

## Architecture Decisions
- [{timestamp}] {snippet}
...

## Common Errors
- "{error_text}" — {occurrences} occurrences across {sessions} sessions
...

## Cost Profile
- Exploration: {exploration_pct}% | Mutation: {mutation_pct}% | Execution: {execution_pct}%
{recommendation if any}
```

### JSON output format:

Return `json.dumps(data, indent=2, default=str)` where data is:
```python
{
    "project": project,
    "overview": _project_overview(db, project),
    "key_files": _key_files(db, project),
    "architecture_patterns": _architecture_patterns(db, project),
    "common_errors": _common_errors(db, project),
    "cost_profile": _cost_profile(db, project),
}
```

### Dependencies:
- `engram.recall.session_db.SessionDB` for DB access
- `engram.stats.compute_project_stats` for cost profile
- Use `db._connect()` context manager for all DB access
- Use `db.search()` for FTS5 architecture pattern search

---

## Task 2: Brief Tests

**New file:** `tests/test_brief.py`

### Test fixtures needed:

Use the `tmp_db` fixture from `conftest.py`. Seed it with test data:

```python
import pytest
from engram.recall.session_db import SessionDB
from engram.recall.artifact_extractor import ArtifactExtractor


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
                (session_id, f"/tmp/{session_id}.jsonl", "test-project",
                 10 + i * 5, f"2026-02-{18+i}T10:00:00Z", f"2026-02-{18+i}T11:00:00Z"),
            )

            # Messages with tool calls
            messages = [
                (session_id, j, "assistant",
                 f'{{"file_path": "/src/app.ts"}}' if j % 3 == 0 else f"Working on feature {j}",
                 f"2026-02-{18+i}T10:{j:02d}:00Z",
                 "Read" if j % 3 == 0 else ("Edit" if j % 3 == 1 else None),
                 1000 * (j + 1), 100 * (j + 1), 500, 0)
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
                    (session_id, "error", "TypeError: Cannot read property 'id' of undefined", None, 90 + i),
                )

    return db
```

### Test assertions:

```python
from engram.brief import (
    _project_overview,
    _key_files,
    _architecture_patterns,
    _common_errors,
    _cost_profile,
    generate_brief,
)


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
```

---

## Task 3: Artifact Completeness Benchmark

**New file:** `tests/test_benchmark_artifacts.py`

This benchmark measures what percentage of tool calls the artifact extractor captures.

```python
"""Benchmark: Artifact extraction completeness.

Measures: What % of tool calls in sessions get captured as artifacts?
Target: >80%
"""

import pytest
from engram.recall.session_db import SessionDB
from engram.recall.artifact_extractor import ArtifactExtractor


@pytest.fixture
def benchmark_db(tmp_db):
    """DB with known tool calls for benchmarking extraction completeness."""
    db = tmp_db
    session_id = "benchmark-artifacts-001"

    with db._connect() as conn:
        conn.execute(
            """INSERT INTO sessions
               (session_id, filepath, project, message_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, "/tmp/bench.jsonl", "bench-project", 20,
             "2026-02-20T10:00:00Z", "2026-02-20T11:00:00Z"),
        )

        # Insert messages with known tool calls
        # These are the "ground truth" tool calls
        tool_messages = [
            # Read tool — should produce file_read artifact
            (session_id, 0, "assistant", '{"file_path": "/src/app.ts"}', None, "Read", 100, 50, 0, 0),
            # Edit tool — should produce file_write artifact
            (session_id, 1, "assistant", '{"file_path": "/src/app.ts", "old_string": "a", "new_string": "b"}', None, "Edit", 100, 50, 0, 0),
            # Write tool — should produce file_create artifact
            (session_id, 2, "assistant", '{"file_path": "/src/new.ts", "content": "hello"}', None, "Write", 100, 50, 0, 0),
            # Bash tool — should produce command artifact
            (session_id, 3, "assistant", '{"command": "npm test"}', None, "Bash", 100, 50, 0, 0),
            # Glob tool — should produce file_read artifact
            (session_id, 4, "assistant", '{"pattern": "**/*.ts"}', None, "Glob", 100, 50, 0, 0),
            # Grep tool — should produce file_read artifact
            (session_id, 5, "assistant", '{"pattern": "TODO", "path": "/src"}', None, "Grep", 100, 50, 0, 0),
            # MCP tool — should produce api_call artifact
            (session_id, 6, "assistant", '{"query": "search"}', None, "mcp_noodlbox", 100, 50, 0, 0),
            # No tool — should NOT produce artifact
            (session_id, 7, "assistant", "Just thinking about the code...", None, None, 100, 50, 0, 0),
            # Error message — should produce error artifact
            (session_id, 8, "assistant", "Error: Module not found", None, None, 100, 50, 0, 0),
            # Another Read
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


EXPECTED_TOOL_CALL_COUNT = 8  # Read, Edit, Write, Bash, Glob, Grep, mcp_noodlbox, Read (2nd)
EXPECTED_ERROR_COUNT = 1


def test_artifact_completeness(benchmark_db):
    """Benchmark: artifact extraction captures >80% of tool calls."""
    extractor = ArtifactExtractor(benchmark_db)
    artifacts = extractor.extract_session("benchmark-artifacts-001")

    tool_artifacts = [a for a in artifacts if a["artifact_type"] != "error"]
    error_artifacts = [a for a in artifacts if a["artifact_type"] == "error"]

    completeness = len(tool_artifacts) / EXPECTED_TOOL_CALL_COUNT
    error_detection = len(error_artifacts) / EXPECTED_ERROR_COUNT if EXPECTED_ERROR_COUNT > 0 else 1.0

    print(f"\n--- Artifact Completeness Benchmark ---")
    print(f"Tool calls expected: {EXPECTED_TOOL_CALL_COUNT}")
    print(f"Tool artifacts found: {len(tool_artifacts)}")
    print(f"Completeness: {completeness:.0%}")
    print(f"Error detection: {error_detection:.0%}")
    print(f"Target: >80%")
    print(f"Result: {'PASS' if completeness >= 0.80 else 'FAIL'}")

    assert completeness >= 0.80, f"Artifact completeness {completeness:.0%} < 80% target"


def test_artifact_types_correct(benchmark_db):
    """Verify extracted artifacts have correct types."""
    extractor = ArtifactExtractor(benchmark_db)
    artifacts = extractor.extract_session("benchmark-artifacts-001")

    type_map = {a["target"]: a["artifact_type"] for a in artifacts if a["artifact_type"] != "error"}

    # Verify Read -> file_read
    assert type_map.get("/src/app.ts") == "file_read" or type_map.get("/src/db.py") == "file_read"

    # Verify Bash -> command
    assert type_map.get("npm test") == "command"

    # Verify mcp_ -> api_call
    assert type_map.get("mcp_noodlbox") == "api_call"
```

---

## Task 4: Search Precision Benchmark

**New file:** `tests/test_benchmark_search.py`

This benchmark measures FTS5 search precision against known ground truth.

```python
"""Benchmark: FTS5 search precision.

Measures: Of the top 5 search results, how many are truly relevant?
Target: >70% precision@5
"""

import pytest
from engram.recall.session_db import SessionDB


@pytest.fixture
def search_db(tmp_db):
    """DB with ground truth search data."""
    db = tmp_db

    # Session 1: About authentication
    with db._connect() as conn:
        conn.execute(
            """INSERT INTO sessions (session_id, filepath, project, message_count, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("search-bench-auth", "/tmp/auth.jsonl", "bench", 5, "2026-02-20T10:00:00Z"),
        )
        auth_messages = [
            ("search-bench-auth", 0, "user", "Fix the JWT authentication bug in login handler", None, None, 0, 0, 0, 0),
            ("search-bench-auth", 1, "assistant", "I'll look at the auth middleware and JWT token validation", None, "Read", 0, 0, 0, 0),
            ("search-bench-auth", 2, "assistant", "The JWT secret is not being loaded from env correctly", None, None, 0, 0, 0, 0),
        ]
        conn.executemany(
            """INSERT INTO messages (session_id, sequence, role, content, timestamp,
                                    tool_name, token_usage_in, token_usage_out,
                                    cache_read_tokens, cache_create_tokens)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            auth_messages,
        )

        # Session 2: About database queries
        conn.execute(
            """INSERT INTO sessions (session_id, filepath, project, message_count, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("search-bench-db", "/tmp/db.jsonl", "bench", 5, "2026-02-20T11:00:00Z"),
        )
        db_messages = [
            ("search-bench-db", 0, "user", "Optimize the database query for user profiles", None, None, 0, 0, 0, 0),
            ("search-bench-db", 1, "assistant", "The SQL query is doing a full table scan, needs an index", None, None, 0, 0, 0, 0),
            ("search-bench-db", 2, "assistant", "Added index on users.email column for faster lookups", None, None, 0, 0, 0, 0),
        ]
        conn.executemany(
            """INSERT INTO messages (session_id, sequence, role, content, timestamp,
                                    tool_name, token_usage_in, token_usage_out,
                                    cache_read_tokens, cache_create_tokens)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            db_messages,
        )

        # Session 3: About deployment
        conn.execute(
            """INSERT INTO sessions (session_id, filepath, project, message_count, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("search-bench-deploy", "/tmp/deploy.jsonl", "bench", 5, "2026-02-20T12:00:00Z"),
        )
        deploy_messages = [
            ("search-bench-deploy", 0, "user", "Set up Docker deployment with nginx reverse proxy", None, None, 0, 0, 0, 0),
            ("search-bench-deploy", 1, "assistant", "Creating Dockerfile and docker-compose.yml for the app", None, None, 0, 0, 0, 0),
        ]
        conn.executemany(
            """INSERT INTO messages (session_id, sequence, role, content, timestamp,
                                    tool_name, token_usage_in, token_usage_out,
                                    cache_read_tokens, cache_create_tokens)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            deploy_messages,
        )

    return db


# Ground truth: query -> expected relevant session IDs
GROUND_TRUTH = {
    '"JWT" "authentication"': {"search-bench-auth"},
    '"database" "query"': {"search-bench-db"},
    '"Docker" "deployment"': {"search-bench-deploy"},
    '"SQL" "index"': {"search-bench-db"},
    '"login" "bug"': {"search-bench-auth"},
}


def test_search_precision(search_db):
    """Benchmark: FTS5 search precision@5 against ground truth."""
    total_precision = 0
    queries_tested = 0

    print(f"\n--- Search Precision Benchmark ---")

    for query, expected_sessions in GROUND_TRUTH.items():
        results = search_db.search(query, limit=5)
        if not results:
            print(f"  Query '{query}': no results")
            continue

        result_sessions = {r["session_id"] for r in results}
        relevant = result_sessions & expected_sessions
        precision = len(relevant) / len(results) if results else 0

        print(f"  Query '{query}': precision={precision:.0%} ({len(relevant)}/{len(results)} relevant)")
        total_precision += precision
        queries_tested += 1

    avg_precision = total_precision / queries_tested if queries_tested > 0 else 0
    print(f"\nAverage precision@5: {avg_precision:.0%}")
    print(f"Target: >70%")
    print(f"Result: {'PASS' if avg_precision >= 0.70 else 'FAIL'}")

    assert avg_precision >= 0.70, f"Search precision {avg_precision:.0%} < 70% target"
```

---

## Deliverables

When done:
1. Run existing tests: `pytest tests/ -v` — all must pass (no regressions)
2. Run new tests: `pytest tests/test_brief.py tests/test_benchmark_artifacts.py tests/test_benchmark_search.py -v`
3. `git add engram/brief.py tests/test_brief.py tests/test_benchmark_artifacts.py tests/test_benchmark_search.py`
4. `git commit -m 'feat: engram brief generator + artifact/search benchmarks (v0.3.0)'`
5. Do NOT `git push`
