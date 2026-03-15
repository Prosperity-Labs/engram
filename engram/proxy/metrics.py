"""Session metrics computation from proxy_calls data.

Detects session boundaries (10+ min gap between calls on same project),
computes per-session metrics like turns-to-first-edit, and stores results
in the session_metrics table.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path.home() / ".config" / "engram" / "sessions.db"
SESSION_GAP_MINUTES = 10
EDIT_TOOLS = {"Write", "Edit", "NotebookEdit"}
READ_TOOLS = {"Read", "Glob", "Grep"}


def _get_db(db_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS session_metrics (
            session_id TEXT PRIMARY KEY,
            project TEXT,
            enrichment_variant TEXT,
            turns_to_first_edit INTEGER,
            exploration_turns INTEGER,
            exploration_cost_usd REAL,
            total_turns INTEGER,
            total_cost_usd REAL,
            files_read_before_edit INTEGER,
            errors_count INTEGER,
            outcome TEXT,
            started_at DATETIME,
            ended_at DATETIME,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_session_metrics_project
            ON session_metrics(project);
        CREATE INDEX IF NOT EXISTS idx_session_metrics_variant
            ON session_metrics(enrichment_variant);
    """)


def detect_sessions(conn: sqlite3.Connection) -> list[dict]:
    """Group proxy_calls into sessions using 10-min gap detection.

    Returns list of sessions, each with a list of call dicts.
    """
    rows = conn.execute("""
        SELECT id, timestamp, model, cost_estimate_usd, tools_used,
               stop_reason, session_id, project, enrichment_variant
        FROM proxy_calls
        WHERE project IS NOT NULL
        ORDER BY project, timestamp
    """).fetchall()

    sessions: list[dict] = []
    current: dict | None = None

    for row in rows:
        ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
        project = row["project"]

        # Check if this call belongs to the current session
        if (
            current is not None
            and current["project"] == project
            and (ts - current["last_ts"]) < timedelta(minutes=SESSION_GAP_MINUTES)
        ):
            current["calls"].append(dict(row))
            current["last_ts"] = ts
        else:
            if current is not None:
                sessions.append(current)
            # Use proxy-assigned session_id if available, otherwise generate
            sid = row["session_id"] or f"inferred-{row['id']}"
            current = {
                "session_id": sid,
                "project": project,
                "calls": [dict(row)],
                "first_ts": ts,
                "last_ts": ts,
            }

    if current is not None:
        sessions.append(current)

    return sessions


def compute_metrics(session: dict) -> dict:
    """Compute metrics for a single session."""
    calls = session["calls"]

    total_turns = len(calls)
    total_cost = sum(c["cost_estimate_usd"] or 0 for c in calls)

    # Determine enrichment variant (majority vote across calls)
    variants = [c["enrichment_variant"] for c in calls if c["enrichment_variant"]]
    variant = variants[0] if variants else None

    # Find first edit
    turns_to_first_edit = None
    exploration_turns = total_turns
    exploration_cost = total_cost
    files_read_before_edit = 0
    errors_count = 0

    for i, call in enumerate(calls):
        tools = _parse_tools(call["tools_used"])

        # Count reads before first edit
        if turns_to_first_edit is None:
            files_read_before_edit += sum(1 for t in tools if t in READ_TOOLS)

        if turns_to_first_edit is None and tools & EDIT_TOOLS:
            turns_to_first_edit = i + 1  # 1-indexed
            exploration_turns = i
            exploration_cost = sum(
                c["cost_estimate_usd"] or 0 for c in calls[:i]
            )

        # Count error stops
        if call["stop_reason"] == "error":
            errors_count += 1

    # Determine outcome
    if total_turns >= 3 and calls[-1]["stop_reason"] == "end_turn":
        outcome = "completed"
    elif total_turns <= 2:
        outcome = "abandoned"
    else:
        outcome = "unknown"

    return {
        "session_id": session["session_id"],
        "project": session["project"],
        "enrichment_variant": variant,
        "turns_to_first_edit": turns_to_first_edit,
        "exploration_turns": exploration_turns,
        "exploration_cost_usd": round(exploration_cost, 6),
        "total_turns": total_turns,
        "total_cost_usd": round(total_cost, 6),
        "files_read_before_edit": files_read_before_edit,
        "errors_count": errors_count,
        "outcome": outcome,
        "started_at": session["first_ts"].isoformat(),
        "ended_at": session["last_ts"].isoformat(),
    }


def _parse_tools(tools_json: str | None) -> set[str]:
    if not tools_json:
        return set()
    try:
        tools = json.loads(tools_json)
        return set(tools) if isinstance(tools, list) else set()
    except (json.JSONDecodeError, TypeError):
        return set()


def backfill(db_path: str | None = None) -> list[dict]:
    """Detect sessions and compute metrics for all proxy_calls."""
    conn = _get_db(db_path)
    _ensure_table(conn)

    sessions = detect_sessions(conn)
    results = []

    for session in sessions:
        metrics = compute_metrics(session)
        conn.execute(
            """INSERT OR REPLACE INTO session_metrics
               (session_id, project, enrichment_variant,
                turns_to_first_edit, exploration_turns, exploration_cost_usd,
                total_turns, total_cost_usd, files_read_before_edit,
                errors_count, outcome, started_at, ended_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                metrics["session_id"],
                metrics["project"],
                metrics["enrichment_variant"],
                metrics["turns_to_first_edit"],
                metrics["exploration_turns"],
                metrics["exploration_cost_usd"],
                metrics["total_turns"],
                metrics["total_cost_usd"],
                metrics["files_read_before_edit"],
                metrics["errors_count"],
                metrics["outcome"],
                metrics["started_at"],
                metrics["ended_at"],
            ),
        )
        results.append(metrics)

    conn.commit()
    conn.close()
    return results


def print_comparison(db_path: str | None = None) -> None:
    """Print enrichment variant comparison table."""
    conn = _get_db(db_path)
    _ensure_table(conn)

    rows = conn.execute("""
        SELECT
            COALESCE(enrichment_variant, 'baseline') as variant,
            COUNT(*) as sessions,
            ROUND(AVG(turns_to_first_edit), 1) as avg_turns_to_edit,
            ROUND(AVG(exploration_turns), 1) as avg_explore_turns,
            ROUND(AVG(exploration_cost_usd), 4) as avg_explore_cost,
            ROUND(AVG(total_turns), 1) as avg_total_turns,
            ROUND(AVG(total_cost_usd), 4) as avg_total_cost,
            ROUND(AVG(files_read_before_edit), 1) as avg_reads,
            ROUND(AVG(errors_count), 1) as avg_errors
        FROM session_metrics
        WHERE total_turns >= 3
        GROUP BY enrichment_variant
        ORDER BY variant
    """).fetchall()

    if not rows:
        print("No session metrics found. Run `engram proxy metrics --backfill` first.")
        conn.close()
        return

    # Header
    print(f"{'Variant':<12} {'Sessions':>8} {'Turns→Edit':>10} {'Explore':>8} "
          f"{'Expl$':>8} {'TotalTurns':>10} {'Total$':>8} {'Reads':>6} {'Errors':>6}")
    print("-" * 88)

    for r in rows:
        tte = f"{r['avg_turns_to_edit']}" if r["avg_turns_to_edit"] else "n/a"
        print(
            f"{r['variant']:<12} {r['sessions']:>8} {tte:>10} "
            f"{r['avg_explore_turns']:>8} ${r['avg_explore_cost']:>7.4f} "
            f"{r['avg_total_turns']:>10} ${r['avg_total_cost']:>7.4f} "
            f"{r['avg_reads']:>6} {r['avg_errors']:>6}"
        )

    conn.close()


def print_recent(db_path: str | None = None, limit: int = 20) -> None:
    """Print recent sessions with metrics."""
    conn = _get_db(db_path)
    _ensure_table(conn)

    rows = conn.execute("""
        SELECT session_id, project, enrichment_variant,
               turns_to_first_edit, exploration_turns, exploration_cost_usd,
               total_turns, total_cost_usd, outcome, started_at
        FROM session_metrics
        ORDER BY started_at DESC
        LIMIT ?
    """, (limit,)).fetchall()

    if not rows:
        print("No session metrics found. Run `engram proxy metrics --backfill` first.")
        conn.close()
        return

    print(f"{'Project':<20} {'Variant':<10} {'Turns':>5} {'→Edit':>5} "
          f"{'Cost':>8} {'Outcome':<10} {'Date':<12}")
    print("-" * 80)

    for r in rows:
        proj = (r["project"] or "?")[-20:]
        variant = r["enrichment_variant"] or "base"
        tte = str(r["turns_to_first_edit"]) if r["turns_to_first_edit"] else "-"
        date = (r["started_at"] or "")[:10]
        print(
            f"{proj:<20} {variant:<10} {r['total_turns']:>5} {tte:>5} "
            f"${r['total_cost_usd']:>7.4f} {r['outcome']:<10} {date:<12}"
        )

    conn.close()
