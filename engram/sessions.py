"""Session listing and terminal rendering helpers."""

from __future__ import annotations

from engram.recall.session_db import SessionDB


def list_sessions(
    db: SessionDB,
    project: str | None = None,
    min_messages: int = 0,
    sort_by: str = "recent",
    limit: int = 50,
) -> list[dict]:
    """List sessions with metadata.

    Returns list of dicts:
    {
        "session_id": str,
        "project": str,
        "message_count": int,
        "tokens_in": int,
        "tokens_out": int,
        "tool_calls": int,
        "created_at": str | None,
        "updated_at": str | None,
        "file_size_bytes": int,
    }
    """
    order_by = "s.updated_at DESC"
    if sort_by == "messages":
        order_by = "s.message_count DESC"
    elif sort_by == "tokens":
        order_by = "tokens_in DESC"

    sql = f"""
        SELECT s.session_id, s.project, s.message_count, s.file_size_bytes,
               s.created_at, s.updated_at,
               COALESCE(SUM(m.token_usage_in), 0) as tokens_in,
               COALESCE(SUM(m.token_usage_out), 0) as tokens_out,
               COUNT(CASE WHEN m.tool_name IS NOT NULL THEN 1 END) as tool_calls
        FROM sessions s
        LEFT JOIN messages m ON m.session_id = s.session_id
        WHERE s.message_count > ?
    """
    params: list = [min_messages]

    if project is not None:
        sql += " AND s.project = ?"
        params.append(project)

    sql += f"""
        GROUP BY s.session_id
        ORDER BY {order_by}
        LIMIT ?
    """
    params.append(limit)

    with db._connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [
        {
            "session_id": row["session_id"],
            "project": row["project"],
            "message_count": row["message_count"],
            "tokens_in": row["tokens_in"],
            "tokens_out": row["tokens_out"],
            "tool_calls": row["tool_calls"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "file_size_bytes": row["file_size_bytes"],
        }
        for row in rows
    ]


def _fmt_int(value: int | None) -> str:
    return f"{int(value or 0):,}"


def _fmt_tokens(value: int | None) -> str:
    val = int(value or 0)
    if val >= 1_000_000:
        return f"{val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"{val / 1_000:.1f}K"
    return str(val)


def _fmt_updated(value: str | None) -> str:
    if not value:
        return "-"
    return value.replace("T", " ").replace("Z", "")[:16]


def render_sessions(sessions: list[dict]) -> str:
    """Render session list as terminal-friendly table.

    Format:
    SESSION       PROJECT          MSGS  TOOLS  TOKENS IN   UPDATED
    46971622...   monra-app       1,040    382    68.3M     2026-02-18 19:30
    d534d0a0...   monra-app         931    341    62.3M     2026-02-18 23:20
    ...
    """
    if not sessions:
        return "No sessions found."

    header = (
        f"{'SESSION':<14} "
        f"{'PROJECT':<16} "
        f"{'MSGS':>6} "
        f"{'TOOLS':>6} "
        f"{'TOKENS IN':>10} "
        f"{'UPDATED':<16}"
    )
    lines = [header]
    for row in sessions:
        session_id = (row.get("session_id") or "")[:8] + "..."
        lines.append(
            f"{session_id:<14} "
            f"{(row.get('project') or '-'):16.16} "
            f"{_fmt_int(row.get('message_count')):>6} "
            f"{_fmt_int(row.get('tool_calls')):>6} "
            f"{_fmt_tokens(row.get('tokens_in')):>10} "
            f"{_fmt_updated(row.get('updated_at')):<16}"
        )

    return "\n".join(lines)
