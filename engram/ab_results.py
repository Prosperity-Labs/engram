from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from engram.recall.session_db import SessionDB


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _pct_delta(a: int | float, b: int | float) -> float | None:
    if a == 0:
        return None
    return round(((b - a) / a) * 100, 2)


def _load_checkpoints(db: SessionDB, worktree_id: int) -> list[dict[str, Any]]:
    with db._connect() as conn:
        rows = conn.execute(
            """SELECT id, session_id, artifact_snapshot, created_at, ab_variant_label
               FROM checkpoints
               WHERE worktree_id = ?
               ORDER BY id ASC""",
            (worktree_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        if item.get("artifact_snapshot"):
            try:
                item["artifact_snapshot"] = json.loads(item["artifact_snapshot"])
            except (json.JSONDecodeError, TypeError):
                item["artifact_snapshot"] = None
        out.append(item)
    return out


def _artifact_metrics(db: SessionDB, session_id: str | None) -> dict[str, int]:
    if not session_id:
        return {"tool_calls_count": 0, "artifact_errors": 0, "artifact_file_touches": 0}

    try:
        with db._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN artifact_type != 'error' THEN 1 ELSE 0 END) AS tool_calls_count,
                    SUM(CASE WHEN artifact_type = 'error' THEN 1 ELSE 0 END) AS artifact_errors,
                    COUNT(DISTINCT CASE
                        WHEN artifact_type IN ('file_write', 'file_create') THEN target
                        ELSE NULL
                    END) AS artifact_file_touches
                FROM artifacts
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
    except Exception:
        return {"tool_calls_count": 0, "artifact_errors": 0, "artifact_file_touches": 0}

    return {
        "tool_calls_count": int((row["tool_calls_count"] if row else 0) or 0),
        "artifact_errors": int((row["artifact_errors"] if row else 0) or 0),
        "artifact_file_touches": int((row["artifact_file_touches"] if row else 0) or 0),
    }


def capture_worktree_result(worktree_id: int, db_path: str | Path) -> dict[str, Any]:
    """Compute and persist a compact result summary for one worktree."""
    db = SessionDB(db_path=db_path)
    worktree = db.get_worktree(worktree_id)
    if not worktree:
        raise ValueError(f"Worktree {worktree_id} not found")

    checkpoints = _load_checkpoints(db, worktree_id)
    cycles = db.get_correction_cycles(worktree_id)
    artifact_metrics = _artifact_metrics(db, worktree.get("session_id"))

    files_from_checkpoints: set[str] = set()
    checkpoint_variant = None
    for cp in checkpoints:
        checkpoint_variant = checkpoint_variant or cp.get("ab_variant_label")
        snapshot = cp.get("artifact_snapshot")
        if isinstance(snapshot, list):
            for item in snapshot:
                if isinstance(item, str):
                    files_from_checkpoints.add(item)

    event_times: list[datetime] = []
    for ts in [worktree.get("created_at"), worktree.get("resolved_at")]:
        dt = _parse_iso(ts)
        if dt:
            event_times.append(dt)
    for cp in checkpoints:
        dt = _parse_iso(cp.get("created_at"))
        if dt:
            event_times.append(dt)
    for cc in cycles:
        dt = _parse_iso(cc.get("created_at"))
        if dt:
            event_times.append(dt)

    duration_seconds = 0.0
    if len(event_times) >= 2:
        duration_seconds = (max(event_times) - min(event_times)).total_seconds()

    cycle_errors = sum(1 for c in cycles if c.get("trigger_error"))
    result = {
        "worktree_id": worktree_id,
        "variant_label": worktree.get("ab_variant_label") or checkpoint_variant,
        "status": worktree.get("status"),
        "session_id": worktree.get("session_id"),
        "files_touched": max(len(files_from_checkpoints), artifact_metrics["artifact_file_touches"]),
        "errors_hit": cycle_errors + artifact_metrics["artifact_errors"],
        "tool_calls_count": artifact_metrics["tool_calls_count"],
        "duration_seconds": round(duration_seconds, 2),
        "checkpoints_count": len(checkpoints),
        "correction_cycles_count": len(cycles),
    }
    db.store_worktree_results(worktree_id, result)
    return result


def compare_results(worktree_id_a: int, worktree_id_b: int, db_path: str | Path) -> dict[str, Any]:
    """Compare two stored worktree results and report winners + deltas."""
    db = SessionDB(db_path=db_path)
    result_a = db.get_worktree_results(worktree_id_a) or capture_worktree_result(worktree_id_a, db_path)
    result_b = db.get_worktree_results(worktree_id_b) or capture_worktree_result(worktree_id_b, db_path)

    def _winner(metric: str, prefer: str) -> str | None:
        a_val = result_a.get(metric)
        b_val = result_b.get(metric)
        if a_val is None or b_val is None or a_val == b_val:
            return None
        if prefer == "lower":
            return "A" if a_val < b_val else "B"
        return "A" if a_val > b_val else "B"

    return {
        "worktree_a": {
            "id": worktree_id_a,
            "variant_label": result_a.get("variant_label"),
            "results": result_a,
        },
        "worktree_b": {
            "id": worktree_id_b,
            "variant_label": result_b.get("variant_label"),
            "results": result_b,
        },
        "comparison": {
            "faster": _winner("duration_seconds", "lower"),
            "fewer_errors": _winner("errors_hit", "lower"),
            "more_files_touched": _winner("files_touched", "higher"),
            "tool_efficiency": _winner("tool_calls_count", "lower"),
            "delta_pct_b_vs_a": {
                "duration_seconds": _pct_delta(
                    float(result_a.get("duration_seconds", 0)),
                    float(result_b.get("duration_seconds", 0)),
                ),
                "errors_hit": _pct_delta(
                    int(result_a.get("errors_hit", 0)),
                    int(result_b.get("errors_hit", 0)),
                ),
                "files_touched": _pct_delta(
                    int(result_a.get("files_touched", 0)),
                    int(result_b.get("files_touched", 0)),
                ),
                "tool_calls_count": _pct_delta(
                    int(result_a.get("tool_calls_count", 0)),
                    int(result_b.get("tool_calls_count", 0)),
                ),
            },
        },
    }
