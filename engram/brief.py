from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from engram.recall.session_db import SessionDB
from engram.stats import compute_project_stats


DECISION_KEYWORDS = [
    "chose",
    "decided",
    "because",
    "instead of",
    "trade-off",
    "architecture",
    "pattern",
    "approach",
    "design",
]


def _project_overview(db: SessionDB, project: str) -> dict:
    """Gather high-level project metrics."""
    sql = """
SELECT COUNT(DISTINCT s.session_id) as sessions,
       SUM(s.message_count) as messages,
       COALESCE(SUM(m.token_usage_in), 0) as tokens_in,
       COALESCE(SUM(m.token_usage_out), 0) as tokens_out,
       MIN(s.created_at) as first_session,
       MAX(s.updated_at) as last_session
FROM sessions s
LEFT JOIN messages m ON m.session_id = s.session_id
WHERE s.project = ?
"""
    with db._connect() as conn:
        row = conn.execute(sql, (project,)).fetchone()

    sessions = int((row["sessions"] if row else 0) or 0)
    messages = int((row["messages"] if row else 0) or 0)
    tokens_in = int((row["tokens_in"] if row else 0) or 0)
    tokens_out = int((row["tokens_out"] if row else 0) or 0)
    cost = (tokens_in * 15.0 + tokens_out * 75.0) / 1_000_000

    return {
        "sessions": sessions,
        "messages": messages,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_estimate": cost,
        "first_session": (row["first_session"] if row else None),
        "last_session": (row["last_session"] if row else None),
    }


def _key_files(db: SessionDB, project: str) -> dict:
    """Find most-accessed and most-modified files from artifacts table."""
    sql_read = """
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
"""
    sql_modified = """
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
"""
    with db._connect() as conn:
        read_rows = conn.execute(sql_read, (project,)).fetchall()
        modified_rows = conn.execute(sql_modified, (project,)).fetchall()

    def _rows_to_list(rows) -> list[dict]:
        return [
            {
                "path": row["path"],
                "count": int(row["count"] or 0),
                "sessions": int(row["sessions"] or 0),
            }
            for row in rows
        ]

    return {
        "most_read": _rows_to_list(read_rows),
        "most_modified": _rows_to_list(modified_rows),
    }


def _architecture_patterns(db: SessionDB, project: str) -> list[dict]:
    """Search for architecture decisions in session content."""
    deduped: dict[str, dict] = {}

    for keyword in DECISION_KEYWORDS:
        try:
            results = db.search(keyword, limit=3, session_id=None)
        except Exception:
            continue
        for result in results:
            if result.get("project") != project:
                continue
            content = (result.get("content") or "").strip()
            if not content:
                continue
            content_prefix = content[:200]
            if content_prefix in deduped:
                existing_rank = deduped[content_prefix]["_rank"]
                if result["rank"] < existing_rank:
                    deduped[content_prefix]["_rank"] = result["rank"]
                    deduped[content_prefix]["timestamp"] = result.get("timestamp")
                    deduped[content_prefix]["session_id"] = result.get("session_id")
                continue
            deduped[content_prefix] = {
                "snippet": content_prefix,
                "timestamp": result.get("timestamp"),
                "session_id": result.get("session_id"),
                "_rank": result["rank"],
            }

    ranked = sorted(deduped.values(), key=lambda item: item["_rank"])
    return [
        {
            "snippet": item["snippet"],
            "timestamp": item["timestamp"],
            "session_id": item["session_id"],
        }
        for item in ranked[:10]
    ]


def _common_errors(db: SessionDB, project: str) -> list[dict]:
    """Find recurring errors from artifacts table."""
    sql = """
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
"""
    with db._connect() as conn:
        rows = conn.execute(sql, (project,)).fetchall()

    return [
        {
            "error_text": row["error_text"],
            "occurrences": int(row["occurrences"] or 0),
            "sessions": int(row["sessions"] or 0),
        }
        for row in rows
    ]


def _cost_profile(db: SessionDB, project: str) -> dict:
    """Reuse compute_project_stats to get cost breakdown."""
    all_stats = compute_project_stats(db)
    project_stats = next((s for s in all_stats if s["project"] == project), None)
    if project_stats is None:
        return {
            "exploration_pct": 0,
            "mutation_pct": 0,
            "execution_pct": 0,
            "recommendation": None,
        }

    exploration_pct = int(project_stats["exploration_ratio"] * 100)
    mutation_pct = int(project_stats["mutation_ratio"] * 100)
    execution_pct = int(project_stats["execution_ratio"] * 100)
    recommendation = None
    if exploration_pct > 30:
        recommendation = (
            "High exploration ratio — consider adding a code index MCP server to reduce file discovery cost."
        )

    return {
        "exploration_pct": exploration_pct,
        "mutation_pct": mutation_pct,
        "execution_pct": execution_pct,
        "recommendation": recommendation,
    }


def _dangerous_files(db: SessionDB, project: str) -> list[dict]:
    """Find files with high error-to-write ratios — the most dangerous files.

    Error artifacts store message content as their target (not file paths),
    so we correlate by session: files written in sessions that also had errors.
    """
    sql = """
    SELECT w.target as path,
           COUNT(DISTINCT w.id) as writes,
           COUNT(DISTINCT e.id) as errors,
           COUNT(DISTINCT w.session_id) as sessions
    FROM artifacts w
    JOIN sessions s ON s.session_id = w.session_id
    LEFT JOIN artifacts e ON e.session_id = w.session_id
                          AND e.artifact_type = 'error'
    WHERE s.project = ?
      AND w.artifact_type IN ('file_write', 'file_create')
    GROUP BY w.target
    HAVING errors > 0
    ORDER BY CAST(errors AS FLOAT) / MAX(writes, 1) DESC
    LIMIT 5
    """
    with db._connect() as conn:
        rows = conn.execute(sql, (project,)).fetchall()

    return [
        {
            "path": row["path"],
            "errors": int(row["errors"] or 0),
            "writes": int(row["writes"] or 0),
            "sessions": int(row["sessions"] or 0),
            "ratio": f"{int(row['errors'] or 0)}:{max(int(row['writes'] or 0), 1)}",
        }
        for row in rows
    ]


def _co_change_clusters(db: SessionDB, project: str) -> list[list[str]]:
    """Find files that are frequently modified together in the same session."""
    sql = """
    SELECT a1.target as file_a, a2.target as file_b,
           COUNT(DISTINCT a1.session_id) as co_sessions
    FROM artifacts a1
    JOIN artifacts a2 ON a1.session_id = a2.session_id AND a1.target < a2.target
    JOIN sessions s ON s.session_id = a1.session_id
    WHERE s.project = ?
      AND a1.artifact_type IN ('file_write', 'file_create')
      AND a2.artifact_type IN ('file_write', 'file_create')
    GROUP BY a1.target, a2.target
    HAVING co_sessions >= 2
    ORDER BY co_sessions DESC
    LIMIT 5
    """
    with db._connect() as conn:
        rows = conn.execute(sql, (project,)).fetchall()

    clusters = []
    for row in rows:
        clusters.append([row["file_a"], row["file_b"]])
    return clusters


def generate_slim_brief(
    db: SessionDB,
    project: str,
) -> str:
    """Generate a compact brief (<500 tokens) that reduces warmup exploration.

    Addresses the warmup tax: 76% of first 10 messages are pure exploration.
    Tells the agent where things are and what happened last, not just what's dangerous.

    Sections:
    1. Last session — continuation context
    2. Key files — most-edited files so agent doesn't re-discover them
    3. Danger zones — files with high error ratios
    4. Co-change clusters — files that break together
    5. Architecture decisions — load-bearing choices
    """
    from engram.hooks import last_session_summary

    key_files = _key_files(db, project)
    dangerous = _dangerous_files(db, project)
    clusters = _co_change_clusters(db, project)
    arch = _architecture_patterns(db, project)
    last_session = last_session_summary(db, project)

    lines = [f"# {project} — Engram Brief"]

    # Last session — so agent can continue where the previous one left off
    if last_session:
        lines.append("")
        lines.append(f"> {last_session}")

    # Key files — reduces discovery exploration
    if key_files["most_modified"]:
        lines.append("")
        lines.append("## Key Files")
        for f in key_files["most_modified"][:5]:
            short = Path(f["path"]).name
            lines.append(f"- `{short}` — {f['count']} edits, {f['sessions']} sessions")

    # Danger zones — files that tend to cause errors
    if dangerous:
        lines.append("")
        lines.append("## Danger Zones")
        for f in dangerous[:3]:
            short = Path(f['path']).name
            lines.append(f"- `{short}` — {f['ratio']} error/write, {f['sessions']} sessions")

    # Co-change clusters — files that should be edited together
    if clusters:
        lines.append("")
        lines.append("## Co-Change Clusters")
        for cluster in clusters[:3]:
            names = [Path(p).name for p in cluster]
            lines.append(f"- {' + '.join(f'`{n}`' for n in names)}")

    # Architecture decisions — load-bearing choices
    if arch:
        lines.append("")
        lines.append("## Key Decisions")
        for item in arch[:3]:
            snippet = item["snippet"][:120].replace("\n", " ")
            lines.append(f"- {snippet}")

    return "\n".join(lines)


def generate_brief(
    db: SessionDB,
    project: str,
    format: str = "markdown",
    slim: bool = False,
) -> str:
    """Orchestrate all data-gathering functions and produce the brief."""
    if slim:
        return generate_slim_brief(db, project)
    overview = _project_overview(db, project)
    key_files = _key_files(db, project)
    architecture_patterns = _architecture_patterns(db, project)
    common_errors = _common_errors(db, project)
    cost_profile = _cost_profile(db, project)

    if format == "json":
        data = {
            "project": project,
            "overview": overview,
            "key_files": key_files,
            "architecture_patterns": architecture_patterns,
            "common_errors": common_errors,
            "cost_profile": cost_profile,
        }
        return json.dumps(data, indent=2, default=str)

    if format != "markdown":
        raise ValueError("format must be 'markdown' or 'json'")

    lines = [
        f"# Project Brief: {project}",
        (
            f"> Auto-generated by Engram from {overview['sessions']} sessions "
            f"({overview['first_session']} to {overview['last_session']})"
        ),
        "",
        "## Overview",
        (
            f"- **Sessions:** {overview['sessions']} | **Messages:** {overview['messages']} | "
            f"**Est. Cost:** ${overview['cost_estimate']:.2f}"
        ),
        "",
        "## Key Files",
        "### Most Modified",
    ]

    if key_files["most_modified"]:
        for item in key_files["most_modified"]:
            lines.append(
                f"- `{item['path']}` ({item['count']} edits across {item['sessions']} sessions)"
            )
    else:
        lines.append("- None")

    lines.extend(["", "### Most Read"])
    if key_files["most_read"]:
        for item in key_files["most_read"]:
            lines.append(
                f"- `{item['path']}` ({item['count']} reads across {item['sessions']} sessions)"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Architecture Decisions"])
    if architecture_patterns:
        for item in architecture_patterns:
            lines.append(f"- [{item['timestamp']}] {item['snippet']}")
    else:
        lines.append("- None")

    lines.extend(["", "## Common Errors"])
    if common_errors:
        for item in common_errors:
            lines.append(
                f'- "{item["error_text"]}" — {item["occurrences"]} occurrences across {item["sessions"]} sessions'
            )
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Cost Profile",
            (
                f"- Exploration: {cost_profile['exploration_pct']}% | "
                f"Mutation: {cost_profile['mutation_pct']}% | "
                f"Execution: {cost_profile['execution_pct']}%"
            ),
        ]
    )
    if cost_profile["recommendation"]:
        lines.append(cost_profile["recommendation"])

    return "\n".join(lines)
