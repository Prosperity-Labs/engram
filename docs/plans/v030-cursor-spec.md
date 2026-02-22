# Agent Spec: Cursor — CLI Wiring + Token/Recovery Benchmarks + Runner

> **Branch:** `feat/brief-and-benchmarks`
> **Agent:** Cursor
> **Scope:** `engram/cli.py` (modify) + `tests/test_benchmark_tokens.py` (new) + `tests/test_benchmark_recovery.py` (new) + `benchmark/run_benchmarks.py` (new)

---

## Context

Codex is building `engram/brief.py` with the following public API:

```python
from engram.brief import generate_brief
from engram.recall.session_db import SessionDB

db = SessionDB()
markdown = generate_brief(db, project="my-project", format="markdown")
json_str = generate_brief(db, project="my-project", format="json")
```

Your job: wire this into the CLI and build the remaining benchmarks + runner.

The CLI pattern is in `engram/cli.py`. All commands follow the same structure:
1. `cmd_xxx(args)` function
2. Argparse subparser in `main()`
3. `p_xxx.set_defaults(func=cmd_xxx)`

Current commands: install, monitor, search, costs, insights, stats, sessions, artifacts, export, clean-names, reindex (11 total).

---

## Task 1: CLI Wiring for `engram brief`

**Modify:** `engram/cli.py`

### Add `cmd_brief` function:

```python
def cmd_brief(args: argparse.Namespace) -> None:
    """Generate a project brief from session history."""
    from .recall.session_db import SessionDB
    from .brief import generate_brief

    db = SessionDB()

    # Determine project — use --project or auto-detect from available projects
    project = args.project
    if not project:
        with db._connect() as conn:
            projects = [
                row["project"]
                for row in conn.execute(
                    """SELECT project, COUNT(*) as cnt
                       FROM sessions
                       WHERE project IS NOT NULL
                       GROUP BY project
                       ORDER BY cnt DESC
                       LIMIT 1"""
                ).fetchall()
            ]
        if projects:
            project = projects[0]
        else:
            print("No projects found. Run `engram install` first.")
            return

    result = generate_brief(db, project=project, format=args.format)

    if args.output:
        from pathlib import Path
        Path(args.output).write_text(result)
        print(f"Brief written to {args.output}")
    else:
        print(result)
```

### Add subparser in `main()`:

Add this block after the `reindex` subparser (before `args = parser.parse_args()`):

```python
# brief
p_brief = subparsers.add_parser("brief", help="Generate project brief from session history")
p_brief.add_argument("--project", "-p", help="Project name (auto-detects if omitted)")
p_brief.add_argument("--format", "-f", choices=["markdown", "json"], default="markdown",
                      help="Output format (default: markdown)")
p_brief.add_argument("--output", "-o", help="Write to file instead of stdout")
p_brief.set_defaults(func=cmd_brief)
```

### Verification:

```bash
engram brief --help           # shows usage
engram brief --project test   # prints markdown
engram brief --format json    # prints JSON
engram brief -o /tmp/brief.md # writes to file
```

---

## Task 2: Token Savings Benchmark

**New file:** `tests/test_benchmark_tokens.py`

This benchmark measures: if the brief existed at session start, what % of file reads would it have preempted? (Because the agent wouldn't need to discover those files — the brief already told it.)

```python
"""Benchmark: Token savings from brief.

Measures: What % of file_read artifacts would be preempted by the brief?
Logic: If a file appears in the brief's "Key Files" section, any read of that file
in the first N messages of a session could have been avoided.
Target: >50%
"""

import pytest
from engram.recall.session_db import SessionDB
from engram.recall.artifact_extractor import ArtifactExtractor
from engram.brief import _key_files


@pytest.fixture
def token_bench_db(tmp_db):
    """DB with sessions that have file_read artifacts for benchmarking."""
    db = tmp_db

    # Create 3 sessions with overlapping file reads
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

            # Simulate messages — first 10 are "exploration" (file reads)
            messages = []
            for j in range(20):
                if j < 10:
                    # Exploration phase: reading common files
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

    # Extract artifacts
    extractor = ArtifactExtractor(db)
    for i in range(3):
        extractor.extract_session(f"token-bench-{i:03d}")

    return db


# "Exploration window" = first N messages of a session
EXPLORATION_WINDOW = 10


def test_token_savings(token_bench_db):
    """Benchmark: brief preempts >50% of exploration file reads."""
    db = token_bench_db

    # Get key files that would appear in the brief
    key_files_data = _key_files(db, "token-project")
    brief_files = set()
    for f in key_files_data["most_read"]:
        brief_files.add(f["path"])
    for f in key_files_data["most_modified"]:
        brief_files.add(f["path"])

    # Count file reads in exploration window across all sessions
    total_reads = 0
    preempted_reads = 0

    with db._connect() as conn:
        sessions = conn.execute(
            "SELECT session_id FROM sessions WHERE project = ?",
            ("token-project",),
        ).fetchall()

        for session_row in sessions:
            sid = session_row["session_id"]
            reads = conn.execute(
                """SELECT a.target
                   FROM artifacts a
                   WHERE a.session_id = ?
                     AND a.artifact_type = 'file_read'
                     AND a.sequence < ?""",
                (sid, EXPLORATION_WINDOW),
            ).fetchall()

            for read in reads:
                total_reads += 1
                if read["target"] in brief_files:
                    preempted_reads += 1

    savings = preempted_reads / total_reads if total_reads > 0 else 0

    print(f"\n--- Token Savings Benchmark ---")
    print(f"Total exploration reads: {total_reads}")
    print(f"Would be preempted by brief: {preempted_reads}")
    print(f"Savings: {savings:.0%}")
    print(f"Brief files: {brief_files}")
    print(f"Target: >50%")
    print(f"Result: {'PASS' if savings >= 0.50 else 'FAIL'}")

    assert savings >= 0.50, f"Token savings {savings:.0%} < 50% target"
```

---

## Task 3: Context Recovery Benchmark

**New file:** `tests/test_benchmark_recovery.py`

This benchmark measures: can Engram's stored data answer basic project questions?

```python
"""Benchmark: Context recovery from Engram data.

Measures: Can we answer basic project questions from stored session data?
Target: >60%

These are deterministic checks — no LLM needed. We verify that Engram's
stored data (sessions, artifacts, search) contains the information needed
to answer common project questions.
"""

import pytest
from engram.recall.session_db import SessionDB
from engram.recall.artifact_extractor import ArtifactExtractor
from engram.stats import compute_project_stats


@pytest.fixture
def recovery_db(tmp_db):
    """DB with rich session data for recovery testing."""
    db = tmp_db

    # Session about auth feature
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

        # Session about database
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

    # Extract artifacts
    extractor = ArtifactExtractor(db)
    extractor.extract_session("recovery-auth")
    extractor.extract_session("recovery-db")

    return db


# Questions and how to verify them
RECOVERY_CHECKS = [
    {
        "question": "How many sessions exist for this project?",
        "check": lambda db: len(db.search('"recovery"', limit=100)) > 0
                 or _session_count(db, "recovery-project") > 0,
        "description": "Session count is recoverable",
    },
    {
        "question": "What files were modified?",
        "check": lambda db: _has_write_artifacts(db, "recovery-project"),
        "description": "Modified files are tracked",
    },
    {
        "question": "Were there any errors?",
        "check": lambda db: _has_error_artifacts(db, "recovery-project"),
        "description": "Errors are captured",
    },
    {
        "question": "What tools were used most?",
        "check": lambda db: _has_tool_stats(db, "recovery-project"),
        "description": "Tool usage stats available",
    },
    {
        "question": "Can we find authentication-related sessions?",
        "check": lambda db: len(db.search('"JWT" "authentication"', limit=5)) > 0,
        "description": "Topic search works",
    },
]


def _session_count(db, project):
    with db._connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM sessions WHERE project = ?",
            (project,),
        ).fetchone()
        return row["cnt"]


def _has_write_artifacts(db, project):
    extractor = ArtifactExtractor(db)
    artifacts = extractor.get_artifacts(project=project, artifact_type="file_write")
    return len(artifacts) > 0


def _has_error_artifacts(db, project):
    extractor = ArtifactExtractor(db)
    artifacts = extractor.get_artifacts(project=project, artifact_type="error")
    return len(artifacts) > 0


def _has_tool_stats(db, project):
    stats = compute_project_stats(db)
    project_stats = [s for s in stats if s["project"] == project]
    return len(project_stats) > 0 and project_stats[0]["tool_calls"] > 0


def test_context_recovery(recovery_db):
    """Benchmark: Engram data can answer >60% of project questions."""
    passed = 0
    total = len(RECOVERY_CHECKS)

    print(f"\n--- Context Recovery Benchmark ---")

    for check in RECOVERY_CHECKS:
        try:
            result = check["check"](recovery_db)
            status = "PASS" if result else "FAIL"
            if result:
                passed += 1
        except Exception as e:
            status = f"ERROR: {e}"

        print(f"  {check['description']}: {status}")

    recovery_rate = passed / total if total > 0 else 0

    print(f"\nRecovery rate: {recovery_rate:.0%} ({passed}/{total})")
    print(f"Target: >60%")
    print(f"Result: {'PASS' if recovery_rate >= 0.60 else 'FAIL'}")

    assert recovery_rate >= 0.60, f"Context recovery {recovery_rate:.0%} < 60% target"
```

---

## Task 4: Benchmark Runner

**New file:** `benchmark/run_benchmarks.py`

```python
#!/usr/bin/env python3
"""Engram Benchmark Runner — prints scorecard of all benchmarks."""

import subprocess
import sys
import re
from pathlib import Path


BENCHMARKS = [
    {
        "name": "Token Savings",
        "file": "tests/test_benchmark_tokens.py",
        "target": ">50%",
        "metric": "Savings",
    },
    {
        "name": "Artifact Completeness",
        "file": "tests/test_benchmark_artifacts.py",
        "target": ">80%",
        "metric": "Completeness",
    },
    {
        "name": "Search Precision",
        "file": "tests/test_benchmark_search.py",
        "target": ">70%",
        "metric": "precision",
    },
    {
        "name": "Context Recovery",
        "file": "tests/test_benchmark_recovery.py",
        "target": ">60%",
        "metric": "Recovery rate",
    },
]


def run_benchmark(bench: dict) -> dict:
    """Run a single benchmark and extract score from output."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", bench["file"], "-v", "-s", "--tb=short"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent),
    )

    output = result.stdout + result.stderr
    passed = result.returncode == 0

    # Extract percentage from output
    score = None
    for line in output.split("\n"):
        if bench["metric"] in line and "%" in line:
            match = re.search(r"(\d+)%", line)
            if match:
                score = int(match.group(1))
                break

    return {
        "name": bench["name"],
        "target": bench["target"],
        "score": f"{score}%" if score is not None else "N/A",
        "passed": passed,
        "output": output,
    }


def main():
    print("=" * 60)
    print("  Engram Benchmark Scorecard")
    print("=" * 60)
    print()

    results = []
    for bench in BENCHMARKS:
        print(f"Running: {bench['name']}...", end=" ", flush=True)
        result = run_benchmark(bench)
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"{status} ({result['score']})")

    print()
    print("-" * 60)
    print(f"{'Benchmark':<25} {'Score':<10} {'Target':<10} {'Status':<10}")
    print("-" * 60)

    total_pass = 0
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        if r["passed"]:
            total_pass += 1
        print(f"{r['name']:<25} {r['score']:<10} {r['target']:<10} {status:<10}")

    print("-" * 60)
    print(f"Overall: {total_pass}/{len(results)} benchmarks passing")
    print()

    if total_pass < len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
```

### Make it executable:
```bash
chmod +x benchmark/run_benchmarks.py
```

---

## Deliverables

When done:
1. Run existing tests: `pytest tests/ -v` — all must pass (no regressions)
2. Run new tests: `pytest tests/test_benchmark_tokens.py tests/test_benchmark_recovery.py -v`
3. Test CLI: `engram brief --help`
4. Run benchmark runner: `python benchmark/run_benchmarks.py`
5. `git add engram/cli.py tests/test_benchmark_tokens.py tests/test_benchmark_recovery.py benchmark/run_benchmarks.py`
6. `git commit -m 'feat: brief CLI + token/recovery benchmarks + runner (v0.3.0)'`
7. Do NOT `git push`
