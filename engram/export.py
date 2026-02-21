"""Export session data to JSON or CSV."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from engram.recall.session_db import SessionDB

_EVENT_COLUMNS = [
    "session_id", "project", "sequence", "role", "tool_name",
    "content", "timestamp", "token_usage_in", "token_usage_out",
]

_SESSION_COLUMNS = [
    "session_id", "project", "message_count", "file_size_bytes",
    "created_at", "updated_at",
]


def export_events(
    db: SessionDB,
    format: str = "json",
    project: str | None = None,
    session_id: str | None = None,
    output: str | None = None,
) -> str:
    """Export session events to JSON or CSV.

    Columns: session_id, project, sequence, role, tool_name,
             content (truncated to 500 chars), timestamp,
             token_usage_in, token_usage_out

    Returns the output string (also writes to file if output is set).
    """
    sql = """
        SELECT m.session_id, s.project, m.sequence, m.role, m.tool_name,
               SUBSTR(m.content, 1, 500) as content, m.timestamp,
               m.token_usage_in, m.token_usage_out
        FROM messages m
        LEFT JOIN sessions s ON s.session_id = m.session_id
        WHERE 1=1
    """
    params: list = []

    if project is not None:
        sql += " AND s.project = ?"
        params.append(project)
    if session_id is not None:
        sql += " AND m.session_id = ?"
        params.append(session_id)

    sql += " ORDER BY m.session_id, m.sequence"

    with db._connect() as conn:
        rows = [dict(row) for row in conn.execute(sql, params).fetchall()]

    result = _format(rows, _EVENT_COLUMNS, format)
    if output:
        Path(output).write_text(result, encoding="utf-8")
    return result


def export_sessions(
    db: SessionDB,
    format: str = "json",
    output: str | None = None,
) -> str:
    """Export session metadata to JSON or CSV.

    Columns: session_id, project, message_count, file_size_bytes,
             created_at, updated_at

    Returns the output string.
    """
    sql = """
        SELECT session_id, project, message_count, file_size_bytes,
               created_at, updated_at
        FROM sessions
        ORDER BY updated_at DESC
    """

    with db._connect() as conn:
        rows = [dict(row) for row in conn.execute(sql).fetchall()]

    result = _format(rows, _SESSION_COLUMNS, format)
    if output:
        Path(output).write_text(result, encoding="utf-8")
    return result


def _format(rows: list[dict], columns: list[str], fmt: str) -> str:
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return buf.getvalue()
    return json.dumps(rows, indent=2, default=str)
