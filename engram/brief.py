from __future__ import annotations

import json
from collections import Counter

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


def generate_brief(
    db: SessionDB,
    project: str,
    format: str = "markdown",
) -> str:
    """Orchestrate all data-gathering functions and produce the brief."""
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
