"""A/B experiment runner for enrichment testing.

Creates isolated git worktrees, runs Claude agents through enriched vs baseline
proxies, collects timing/cost/status data, and stores results.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import sqlite3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ArmResult:
    status: str  # passed / failed / error
    duration_ms: int
    cost_usd: float
    output: str
    test_output: str = ""
    session_id: str | None = None
    turn_count: int = 0


@dataclass
class ArmConfig:
    """Configuration for a single experiment arm."""
    label: str  # "enriched" or "baseline"
    worktree: Path
    task_prompt: str
    port: int
    model: str
    budget_usd: float
    test_cmd: str | None


def _repo_root() -> Path:
    out = subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True
    ).strip()
    return Path(out)


def _head_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip()


def _create_worktree(path: Path, commit: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(path), commit],
        check=True,
        capture_output=True,
        text=True,
    )


def _remove_worktree(path: Path) -> None:
    if path.exists():
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(path)],
            capture_output=True,
            text=True,
        )


def _run_claude(
    cwd: Path,
    task: str,
    port: int,
    model: str,
    budget: float,
) -> tuple[str, float]:
    """Run claude -p in a worktree, return (output, duration_seconds)."""
    env = os.environ.copy()
    env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"
    # Disable MCP servers and hooks to keep experiments clean
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"

    cmd = [
        "claude",
        "-p", task,
        "--model", model,
        "--output-format", "text",
        "--max-budget-usd", str(budget),
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--disable-slash-commands",
    ]

    start = time.monotonic()
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,  # 10 minute hard limit
    )
    elapsed = time.monotonic() - start

    output = result.stdout or ""
    if result.returncode != 0 and result.stderr:
        output += f"\n[STDERR]: {result.stderr[-500:]}"

    return output, elapsed


def _run_test(cwd: Path, test_cmd: str) -> tuple[bool, str]:
    """Run a test command in a worktree, return (passed, output)."""
    result = subprocess.run(
        test_cmd,
        shell=True,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, output


def _run_arm(config: ArmConfig) -> ArmResult:
    """Run a single experiment arm end-to-end: claude + test."""
    try:
        output, elapsed = _run_claude(
            config.worktree, config.task_prompt, config.port,
            config.model, config.budget_usd,
        )
        duration_ms = int(elapsed * 1000)

        status = "completed"
        test_output = ""

        if config.test_cmd:
            passed, test_output = _run_test(config.worktree, config.test_cmd)
            status = "passed" if passed else "failed"

        return ArmResult(
            status=status,
            duration_ms=duration_ms,
            cost_usd=0.0,  # filled in later from proxy DB
            output=output,
            test_output=test_output,
        )
    except subprocess.TimeoutExpired:
        return ArmResult(
            status="error",
            duration_ms=600_000,
            cost_usd=0.0,
            output="[TIMEOUT] 10 minute limit exceeded",
        )
    except Exception as e:
        return ArmResult(
            status="error",
            duration_ms=0,
            cost_usd=0.0,
            output=f"[ERROR] {e}",
        )


def _query_proxy_cost_by_variant(
    db_path: Path,
    after_ts: float,
    before_ts: float,
    variant: str | None,
) -> tuple[float, str | None, int]:
    """Query proxy_calls for cost, session_id, and turn count by enrichment_variant.

    variant=None matches baseline (NULL enrichment_variant).
    variant='v1_slim' matches enriched calls.
    Returns (cost, session_id, turn_count).
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        if variant is None:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(cost_estimate_usd), 0) as cost,
                       MAX(session_id) as session_id,
                       COUNT(*) as turn_count
                FROM proxy_calls
                WHERE datetime(timestamp) > datetime(?, 'unixepoch')
                  AND datetime(timestamp) < datetime(?, 'unixepoch')
                  AND enrichment_variant IS NULL
                """,
                (after_ts, before_ts),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(cost_estimate_usd), 0) as cost,
                       MAX(session_id) as session_id,
                       COUNT(*) as turn_count
                FROM proxy_calls
                WHERE datetime(timestamp) > datetime(?, 'unixepoch')
                  AND datetime(timestamp) < datetime(?, 'unixepoch')
                  AND enrichment_variant = ?
                """,
                (after_ts, before_ts, variant),
            ).fetchone()

        if row:
            return row["cost"], row["session_id"], row["turn_count"]
        return 0.0, None, 0
    finally:
        conn.close()


def _categorize_session_length(turn_count: int) -> str:
    """Categorize session by turn count."""
    if turn_count < 10:
        return "short"
    if turn_count <= 30:
        return "medium"
    return "long"


def _compute_outcome(
    e_status: str, b_status: str, e_dur: int, b_dur: int
) -> str:
    e_pass = e_status == "passed"
    b_pass = b_status == "passed"
    if e_pass and not b_pass:
        return "enriched_wins"
    if b_pass and not e_pass:
        return "baseline_wins"
    if not e_pass and not b_pass:
        return "inconclusive"
    if b_dur > 0:
        delta = (b_dur - e_dur) / b_dur * 100
        if delta > 10:
            return "enriched_wins"
        if delta < -10:
            return "baseline_wins"
    return "tie"


def _store_experiment(
    experiment_id: str,
    task_prompt: str,
    complexity: str,
    repo: str,
    model: str,
    enriched: ArmResult,
    baseline: ArmResult,
) -> str:
    """Store experiment result in DB, return outcome."""
    db_path = Path.home() / ".config" / "engram" / "sessions.db"
    schema_path = Path(__file__).parent.parent / "proxy" / "schema.sql"

    duration_delta_pct = None
    if baseline.duration_ms > 0:
        duration_delta_pct = round(
            (baseline.duration_ms - enriched.duration_ms)
            / baseline.duration_ms
            * 100,
            1,
        )

    outcome = _compute_outcome(
        enriched.status, baseline.status,
        enriched.duration_ms, baseline.duration_ms,
    )

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(schema_path.read_text())

        # Migration: add turn count columns if missing
        for col in ["enriched_turn_count INTEGER", "baseline_turn_count INTEGER"]:
            try:
                conn.execute(f"ALTER TABLE experiments ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass

        conn.execute(
            """
            INSERT OR REPLACE INTO experiments
                (experiment_id, task_prompt, task_complexity, repo, agent_type,
                 model, enriched_status, baseline_status,
                 enriched_duration_ms, baseline_duration_ms, duration_delta_pct,
                 enriched_cost_usd, baseline_cost_usd,
                 enriched_session_id, baseline_session_id,
                 enriched_turn_count, baseline_turn_count,
                 outcome)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                experiment_id, task_prompt, complexity, repo, "claude",
                model, enriched.status, baseline.status,
                enriched.duration_ms, baseline.duration_ms, duration_delta_pct,
                enriched.cost_usd, baseline.cost_usd,
                enriched.session_id, baseline.session_id,
                enriched.turn_count, baseline.turn_count,
                outcome,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return outcome


def run_experiment(
    task_prompt: str,
    test_cmd: str | None = None,
    model: str = "sonnet",
    complexity: str = "simple",
    repo: str | None = None,
    cache_gap_s: int = 0,
    budget_usd: float = 2.0,
    enriched_port: int = 9080,
    baseline_port: int = 9081,
    keep_worktrees: bool = False,
    sequential: bool = False,
    randomize_order: bool = False,
) -> dict:
    """Run a paired A/B experiment. Returns result dict."""
    experiment_id = f"exp-{int(time.time() * 1000)}"
    root = _repo_root()
    repo = repo or root.name
    commit = _head_commit()
    db_path = Path.home() / ".config" / "engram" / "sessions.db"

    exp_dir = root / ".engram-experiments" / experiment_id
    wt_enriched = exp_dir / "enriched"
    wt_baseline = exp_dir / "baseline"

    parallel = not sequential

    print(f"\n{'='*60}")
    print(f"  Experiment: {experiment_id}")
    print(f"  Task: {task_prompt[:70]}")
    print(f"  Model: {model} | Complexity: {complexity}")
    print(f"  Mode: {'parallel' if parallel else 'sequential'}")
    print(f"  Commit: {commit[:8]}")
    print(f"{'='*60}\n")

    # Create worktrees
    print("[1/5] Creating worktrees...")
    _create_worktree(wt_enriched, commit)
    _create_worktree(wt_baseline, commit)
    print(f"      enriched: {wt_enriched}")
    print(f"      baseline: {wt_baseline}")

    enriched_config = ArmConfig(
        label="enriched", worktree=wt_enriched, task_prompt=task_prompt,
        port=enriched_port, model=model, budget_usd=budget_usd, test_cmd=test_cmd,
    )
    baseline_config = ArmConfig(
        label="baseline", worktree=wt_baseline, task_prompt=task_prompt,
        port=baseline_port, model=model, budget_usd=budget_usd, test_cmd=test_cmd,
    )

    try:
        ts_before = time.time()

        if parallel:
            # Run both arms in parallel
            print(f"\n[2/5] Running ENRICHED + BASELINE arms in parallel...")
            with ThreadPoolExecutor(max_workers=2) as pool:
                e_future = pool.submit(_run_arm, enriched_config)
                b_future = pool.submit(_run_arm, baseline_config)
                enriched_result = e_future.result()
                baseline_result = b_future.result()
            e_elapsed = enriched_result.duration_ms / 1000
            b_elapsed = baseline_result.duration_ms / 1000
            print(f"      Enriched: {e_elapsed:.1f}s | Baseline: {b_elapsed:.1f}s")
            print(f"[3/5] Cache gap: n/a (parallel mode)")
        else:
            # Sequential mode
            arms = [
                ("ENRICHED", enriched_config),
                ("BASELINE", baseline_config),
            ]
            if randomize_order:
                random.shuffle(arms)

            print(f"\n[2/5] Running {arms[0][0]} arm (port {arms[0][1].port})...")
            first_result = _run_arm(arms[0][1])
            print(f"      Done in {first_result.duration_ms / 1000:.1f}s")

            if cache_gap_s > 0:
                print(f"\n[3/5] Cache gap: waiting {cache_gap_s}s...")
                time.sleep(cache_gap_s)
            else:
                print(f"\n[3/5] Cache gap: skipped")

            print(f"\n      Running {arms[1][0]} arm (port {arms[1][1].port})...")
            second_result = _run_arm(arms[1][1])
            print(f"      Done in {second_result.duration_ms / 1000:.1f}s")

            # Map back to enriched/baseline regardless of order
            if arms[0][0] == "ENRICHED":
                enriched_result, baseline_result = first_result, second_result
            else:
                enriched_result, baseline_result = second_result, first_result

            e_elapsed = enriched_result.duration_ms / 1000
            b_elapsed = baseline_result.duration_ms / 1000

        ts_after = time.time()

        # Query proxy for cost data using variant-based filtering
        print(f"\n[4/5] Querying costs...")
        time.sleep(1)  # allow DB writes to flush
        e_cost, e_session, e_turns = _query_proxy_cost_by_variant(
            db_path, ts_before, ts_after + 1, variant="v1_slim"
        )
        b_cost, b_session, b_turns = _query_proxy_cost_by_variant(
            db_path, ts_before, ts_after + 1, variant=None
        )

        enriched_result.cost_usd = e_cost
        enriched_result.session_id = e_session
        enriched_result.turn_count = e_turns
        baseline_result.cost_usd = b_cost
        baseline_result.session_id = b_session
        baseline_result.turn_count = b_turns

        e_status = enriched_result.status
        b_status = baseline_result.status
        e_duration_ms = enriched_result.duration_ms
        b_duration_ms = baseline_result.duration_ms

        if test_cmd:
            print(f"      Enriched: {'PASSED' if e_status == 'passed' else 'FAILED'}")
            print(f"      Baseline: {'PASSED' if b_status == 'passed' else 'FAILED'}")

        # Store
        print(f"\n[5/5] Storing results...")
        outcome = _store_experiment(
            experiment_id, task_prompt, complexity, repo, model,
            enriched_result, baseline_result,
        )

        # Summary
        delta_pct = (
            (b_duration_ms - e_duration_ms) / b_duration_ms * 100
            if b_duration_ms > 0
            else 0
        )

        GREEN = "\033[32m"
        YELLOW = "\033[33m"
        CYAN = "\033[36m"
        GRAY = "\033[90m"
        BOLD = "\033[1m"
        RESET = "\033[0m"

        outcome_color = {
            "enriched_wins": GREEN,
            "baseline_wins": YELLOW,
            "tie": CYAN,
            "inconclusive": GRAY,
        }.get(outcome, "")

        print(f"\n{'='*60}")
        print(f"  {BOLD}RESULTS{RESET}")
        print(f"{'='*60}")
        print(f"  {'Metric':<20} {'Enriched':>12} {'Baseline':>12} {'Delta':>10}")
        print(f"  {'-'*54}")
        print(f"  {'Status':<20} {e_status:>12} {b_status:>12}")
        print(f"  {'Duration':<20} {e_elapsed:>11.1f}s {b_elapsed:>11.1f}s {delta_pct:>+9.0f}%")
        print(f"  {'Cost':<20} ${e_cost:>10.4f} ${b_cost:>10.4f}")
        print(f"  {'Turns':<20} {e_turns:>12} {b_turns:>12}")
        print(f"  {'Session length':<20} {_categorize_session_length(e_turns):>12} {_categorize_session_length(b_turns):>12}")
        print(f"  {'Outcome':<20} {outcome_color}{outcome}{RESET}")
        print(f"{'='*60}\n")

        return {
            "experiment_id": experiment_id,
            "outcome": outcome,
            "enriched": {"status": e_status, "duration_ms": e_duration_ms, "cost_usd": e_cost, "turn_count": e_turns},
            "baseline": {"status": b_status, "duration_ms": b_duration_ms, "cost_usd": b_cost, "turn_count": b_turns},
            "delta_pct": delta_pct,
        }

    finally:
        if not keep_worktrees:
            print("Cleaning up worktrees...")
            _remove_worktree(wt_enriched)
            _remove_worktree(wt_baseline)
            if exp_dir.exists():
                shutil.rmtree(exp_dir, ignore_errors=True)


# --- Predefined experiment tasks ---

TASKS = [
    {
        "id": "list-projects",
        "prompt": "Add a `list_projects()` method to engram/recall/session_db.py that returns all unique project names from the sessions table, sorted alphabetically. Write pytest tests in tests/test_list_projects.py.",
        "test": "cd {worktree} && python -m pytest tests/test_list_projects.py -x -q 2>&1",
        "complexity": "simple",
    },
    {
        "id": "session-duration",
        "prompt": "Add a `session_duration(session_id: str) -> float | None` method to engram/recall/session_db.py that computes the duration in seconds between the first and last message timestamps for a given session. Return None if the session doesn't exist. Write pytest tests in tests/test_session_duration.py.",
        "test": "cd {worktree} && python -m pytest tests/test_session_duration.py -x -q 2>&1",
        "complexity": "simple",
    },
    {
        "id": "top-models",
        "prompt": "Add a `top_models(limit: int = 5) -> list[tuple[str, int]]` method to engram/recall/session_db.py that returns the most frequently used models across all messages, as (model_name, count) tuples sorted by count descending. Write pytest tests in tests/test_top_models.py.",
        "test": "cd {worktree} && python -m pytest tests/test_top_models.py -x -q 2>&1",
        "complexity": "simple",
    },
    {
        "id": "cost-summary",
        "prompt": "Add a `cost_summary(project: str | None = None) -> dict` method to engram/recall/session_db.py that returns {'total_cost_usd': float, 'total_input_tokens': int, 'total_output_tokens': int, 'session_count': int} aggregated from the sessions table. If project is given, filter to that project. Write pytest tests in tests/test_cost_summary.py.",
        "test": "cd {worktree} && python -m pytest tests/test_cost_summary.py -x -q 2>&1",
        "complexity": "simple",
    },
    {
        "id": "message-search-highlight",
        "prompt": "Add a `search_with_highlights(query: str, limit: int = 10) -> list[dict]` method to engram/recall/session_db.py that uses the existing FTS5 index to search messages and returns results with a 'highlight' field using SQLite's highlight() function (mark matches with **bold**). Each result dict should have: session_id, role, content, highlight, rank. Write pytest tests in tests/test_search_highlight.py.",
        "test": "cd {worktree} && python -m pytest tests/test_search_highlight.py -x -q 2>&1",
        "complexity": "medium",
    },
]
