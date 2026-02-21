"""Project/session analytics and terminal rendering helpers."""

from __future__ import annotations

from engram.recall.session_db import SessionDB


def _safe_ratio(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return num / den


def _bar(ratio: float, width: int = 16) -> str:
    filled = int(ratio * width)
    return "#" * filled + "." * (width - filled)


def _fmt_int(value: int | None) -> str:
    return f"{int(value or 0):,}"


def _fmt_tokens(value: int | None) -> str:
    val = int(value or 0)
    if val >= 1_000_000:
        return f"{val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"{val / 1_000:.1f}K"
    return str(val)


def _row_to_stats(row, top_tools: list[tuple[str, int]]) -> dict:
    messages = int(row["messages"] or 0)
    tokens_in = int(row["tokens_in"] or 0)
    tokens_out = int(row["tokens_out"] or 0)
    tool_calls = int(row["tool_calls"] or 0)
    error_messages = int(row["error_messages"] or 0)
    exploration = int(row["exploration"] or 0)
    mutation = int(row["mutation"] or 0)
    execution = int(row["execution"] or 0)

    return {
        "project": row["project"],
        "sessions": int(row["sessions"] or 0),
        "messages": messages,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_per_message": _safe_ratio(tokens_in + tokens_out, messages),
        "tool_calls": tool_calls,
        "error_messages": error_messages,
        "error_rate": _safe_ratio(error_messages, messages),
        "exploration_ratio": _safe_ratio(exploration, tool_calls),
        "mutation_ratio": _safe_ratio(mutation, tool_calls),
        "execution_ratio": _safe_ratio(execution, tool_calls),
        "top_tools": top_tools,
    }


def compute_project_stats(db: SessionDB) -> list[dict]:
    """Compute per-project analytics."""
    sql = """
SELECT s.project,
       COUNT(DISTINCT s.session_id) as sessions,
       SUM(s.message_count) as messages,
       SUM(m.token_usage_in) as tokens_in,
       SUM(m.token_usage_out) as tokens_out,
       COUNT(CASE WHEN m.tool_name IS NOT NULL THEN 1 END) as tool_calls,
       COUNT(CASE WHEN m.content LIKE '%error%' OR m.content LIKE '%Error%' THEN 1 END) as error_messages,
       COUNT(CASE WHEN m.tool_name IN ('Read', 'Grep', 'Glob') THEN 1 END) as exploration,
       COUNT(CASE WHEN m.tool_name IN ('Edit', 'Write') THEN 1 END) as mutation,
       COUNT(CASE WHEN m.tool_name = 'Bash' THEN 1 END) as execution
FROM sessions s
LEFT JOIN messages m ON m.session_id = s.session_id
GROUP BY s.project
ORDER BY SUM(m.token_usage_in) DESC
"""

    with db._connect() as conn:
        rows = conn.execute(sql).fetchall()
        results = []
        for row in rows:
            top_tool_rows = conn.execute(
                """
SELECT tool_name, COUNT(*) as cnt
FROM messages
WHERE session_id IN (SELECT session_id FROM sessions WHERE project = ?)
  AND tool_name IS NOT NULL
GROUP BY tool_name
ORDER BY cnt DESC
LIMIT 5
""",
                (row["project"],),
            ).fetchall()
            top_tools = [(r["tool_name"], int(r["cnt"])) for r in top_tool_rows]
            results.append(_row_to_stats(row, top_tools))

    return results


def compute_session_stats(db: SessionDB, session_id: str) -> dict:
    """Compute stats for a single session."""
    with db._connect() as conn:
        row = conn.execute(
            """
            SELECT s.project,
                   1 as sessions,
                   s.message_count as messages,
                   SUM(m.token_usage_in) as tokens_in,
                   SUM(m.token_usage_out) as tokens_out,
                   COUNT(CASE WHEN m.tool_name IS NOT NULL THEN 1 END) as tool_calls,
                   COUNT(CASE WHEN m.content LIKE '%error%' OR m.content LIKE '%Error%' THEN 1 END) as error_messages,
                   COUNT(CASE WHEN m.tool_name IN ('Read', 'Grep', 'Glob') THEN 1 END) as exploration,
                   COUNT(CASE WHEN m.tool_name IN ('Edit', 'Write') THEN 1 END) as mutation,
                   COUNT(CASE WHEN m.tool_name = 'Bash' THEN 1 END) as execution
            FROM sessions s
            LEFT JOIN messages m ON m.session_id = s.session_id
            WHERE s.session_id = ?
            GROUP BY s.session_id
            """,
            (session_id,),
        ).fetchone()

        if row is None:
            return {
                "project": None,
                "sessions": 0,
                "messages": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "tokens_per_message": 0.0,
                "tool_calls": 0,
                "error_messages": 0,
                "error_rate": 0.0,
                "exploration_ratio": 0.0,
                "mutation_ratio": 0.0,
                "execution_ratio": 0.0,
                "top_tools": [],
            }

        top_tool_rows = conn.execute(
            """
            SELECT tool_name, COUNT(*) as cnt
            FROM messages
            WHERE session_id = ?
              AND tool_name IS NOT NULL
            GROUP BY tool_name
            ORDER BY cnt DESC
            LIMIT 5
            """,
            (session_id,),
        ).fetchall()

    return _row_to_stats(
        row,
        [(r["tool_name"], int(r["cnt"])) for r in top_tool_rows],
    )


def render_project_stats(stats: list[dict]) -> str:
    """Render stats as a terminal-friendly string with bars."""
    if not stats:
        return "No project stats found."

    lines: list[str] = []
    for s in stats:
        project = s.get("project") or "(none)"
        sessions = int(s.get("sessions") or 0)
        total_tokens = int(s.get("tokens_in") or 0) + int(s.get("tokens_out") or 0)

        lines.append(f"{project} ({sessions} sessions, {_fmt_tokens(total_tokens)} tokens)")
        lines.append(
            f"  Messages:    {_fmt_int(s.get('messages'))}  |  Errors: {int((s.get('error_rate') or 0) * 100)}%"
        )
        lines.append(
            f"  Exploration: {int((s.get('exploration_ratio') or 0) * 100):>2}%  {_bar(float(s.get('exploration_ratio') or 0.0))}"
        )
        lines.append(
            f"  Mutation:    {int((s.get('mutation_ratio') or 0) * 100):>2}%  {_bar(float(s.get('mutation_ratio') or 0.0))}"
        )
        lines.append(
            f"  Execution:   {int((s.get('execution_ratio') or 0) * 100):>2}%  {_bar(float(s.get('execution_ratio') or 0.0))}"
        )

        top_tools = s.get("top_tools") or []
        if top_tools:
            top_tools_text = ", ".join(f"{name} ({count})" for name, count in top_tools[:5])
        else:
            top_tools_text = "None"
        lines.append(f"  Top tools: {top_tools_text}")
        lines.append("")

    return "\n".join(lines).rstrip()
