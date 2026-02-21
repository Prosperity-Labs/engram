"""Extracts tool/action artifacts from indexed session messages."""

from __future__ import annotations

import json
import re

from engram.recall.session_db import SessionDB


_TOOL_USE_RE = re.compile(r"tool_use:(\w+)\(([^)]*)\)")
_PARAM_RE = re.compile(r"(\w+)=([^,]+)")


class ArtifactExtractor:
    def __init__(self, db: SessionDB):
        self.db = db
        self._init_schema()

    def _init_schema(self):
        """Create artifacts table if it doesn't exist."""
        with self.db._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id    TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    target        TEXT NOT NULL,
                    tool_name     TEXT,
                    sequence      INTEGER,
                    context       TEXT,
                    UNIQUE(session_id, artifact_type, target, sequence)
                );

                CREATE INDEX IF NOT EXISTS idx_artifacts_session ON artifacts(session_id);
                CREATE INDEX IF NOT EXISTS idx_artifacts_type ON artifacts(artifact_type);
                CREATE INDEX IF NOT EXISTS idx_artifacts_target ON artifacts(target);
                """
            )

    def _parse_content(self, content: str | None) -> dict:
        if not content:
            return {}

        match = _TOOL_USE_RE.search(content)
        if match:
            params = match.group(2)
            parsed = {}
            for key, val in _PARAM_RE.findall(params):
                parsed[key] = val.strip()
            return parsed

        try:
            value = json.loads(content)
        except json.JSONDecodeError:
            return {}

        return value if isinstance(value, dict) else {}

    def _target_from_message(self, tool_name: str, parsed: dict) -> str | None:
        if tool_name == "Read":
            return parsed.get("file_path")
        if tool_name == "Glob":
            return parsed.get("pattern")
        if tool_name == "Grep":
            pattern = parsed.get("pattern", "")
            path = parsed.get("path", "")
            target = f"{pattern} {path}".strip()
            return target or None
        if tool_name == "Edit":
            return parsed.get("file_path")
        if tool_name == "Write":
            return parsed.get("file_path")
        if tool_name == "Bash":
            return parsed.get("command")
        if tool_name.startswith("mcp_"):
            return tool_name
        return None

    def _artifact_type(self, tool_name: str) -> str | None:
        if tool_name in {"Read", "Glob", "Grep"}:
            return "file_read"
        if tool_name == "Edit":
            return "file_write"
        if tool_name == "Write":
            return "file_create"
        if tool_name == "Bash":
            return "command"
        if tool_name.startswith("mcp_"):
            return "api_call"
        return None

    def extract_session(self, session_id: str) -> list[dict]:
        """Extract artifacts from all messages in a session.

        Returns list of dicts:
        {
            "session_id": str,
            "artifact_type": str,   # file_read, file_write, file_create, command, api_call, error
            "target": str,          # file path, command string, API endpoint
            "tool_name": str,       # original tool name (Read, Edit, Write, Bash, etc.)
            "sequence": int,        # message sequence number
            "context": str | None,  # short context (first 200 chars of surrounding content)
        }
        """
        artifacts: list[dict] = []
        with self.db._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, sequence, role, content, tool_name
                FROM messages
                WHERE session_id = ?
                ORDER BY sequence ASC
                """,
                (session_id,),
            ).fetchall()

            conn.execute("DELETE FROM artifacts WHERE session_id = ?", (session_id,))

            for row in rows:
                content = row["content"] or ""
                tool_name = row["tool_name"] or ""
                sequence = row["sequence"]
                context = content[:200] if content else None

                if tool_name:
                    parsed = self._parse_content(content)
                    artifact_type = self._artifact_type(tool_name)
                    target = self._target_from_message(tool_name, parsed)
                    if artifact_type and target:
                        artifact = {
                            "session_id": session_id,
                            "artifact_type": artifact_type,
                            "target": target,
                            "tool_name": tool_name,
                            "sequence": sequence,
                            "context": context,
                        }
                        artifacts.append(artifact)
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO artifacts
                            (session_id, artifact_type, target, tool_name, sequence, context)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                artifact["session_id"],
                                artifact["artifact_type"],
                                artifact["target"],
                                artifact["tool_name"],
                                artifact["sequence"],
                                artifact["context"],
                            ),
                        )

                if (
                    row["role"] == "assistant"
                    and content
                    and any(tag in content for tag in ("error", "Error", "ERROR"))
                ):
                    artifact = {
                        "session_id": session_id,
                        "artifact_type": "error",
                        "target": content[:200],
                        "tool_name": tool_name or None,
                        "sequence": sequence,
                        "context": context,
                    }
                    artifacts.append(artifact)
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO artifacts
                        (session_id, artifact_type, target, tool_name, sequence, context)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            artifact["session_id"],
                            artifact["artifact_type"],
                            artifact["target"],
                            artifact["tool_name"],
                            artifact["sequence"],
                            artifact["context"],
                        ),
                    )

        return artifacts

    def extract_all(self) -> dict:
        """Extract artifacts from all sessions.
        Returns: {"sessions_processed": int, "artifacts_extracted": int}
        """
        with self.db._connect() as conn:
            session_ids = [
                row["session_id"]
                for row in conn.execute(
                    "SELECT session_id FROM sessions ORDER BY session_id ASC"
                ).fetchall()
            ]

        total = 0
        for session_id in session_ids:
            total += len(self.extract_session(session_id))

        return {"sessions_processed": len(session_ids), "artifacts_extracted": total}

    def get_artifacts(
        self,
        session_id: str | None = None,
        project: str | None = None,
        artifact_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query stored artifacts with optional filters."""
        where = []
        params: list = []

        if session_id:
            where.append("a.session_id = ?")
            params.append(session_id)
        if project:
            where.append("s.project = ?")
            params.append(project)
        if artifact_type:
            where.append("a.artifact_type = ?")
            params.append(artifact_type)

        where_clause = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(limit)

        sql = f"""
            SELECT a.session_id, a.artifact_type, a.target, a.tool_name, a.sequence, a.context
            FROM artifacts a
            LEFT JOIN sessions s ON s.session_id = a.session_id
            {where_clause}
            ORDER BY a.id DESC
            LIMIT ?
        """

        with self.db._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            {
                "session_id": row["session_id"],
                "artifact_type": row["artifact_type"],
                "target": row["target"],
                "tool_name": row["tool_name"],
                "sequence": row["sequence"],
                "context": row["context"],
            }
            for row in rows
        ]

    def summary(self, session_id: str) -> dict:
        """Return artifact summary for a session.
        Returns:
        {
            "files_read": int,
            "files_written": int,
            "files_created": int,
            "commands": int,
            "api_calls": int,
            "errors": int,
            "top_files": list[tuple[str, int]],  # (path, access_count)
            "top_commands": list[tuple[str, int]],
        }
        """
        with self.db._connect() as conn:
            counts = {
                row["artifact_type"]: row["cnt"]
                for row in conn.execute(
                    """
                    SELECT artifact_type, COUNT(*) AS cnt
                    FROM artifacts
                    WHERE session_id = ?
                    GROUP BY artifact_type
                    """,
                    (session_id,),
                ).fetchall()
            }

            top_files = [
                (row["target"], row["cnt"])
                for row in conn.execute(
                    """
                    SELECT target, COUNT(*) AS cnt
                    FROM artifacts
                    WHERE session_id = ?
                    AND artifact_type IN ('file_read', 'file_write', 'file_create')
                    GROUP BY target
                    ORDER BY cnt DESC, target ASC
                    LIMIT 10
                    """,
                    (session_id,),
                ).fetchall()
            ]
            top_commands = [
                (row["target"], row["cnt"])
                for row in conn.execute(
                    """
                    SELECT target, COUNT(*) AS cnt
                    FROM artifacts
                    WHERE session_id = ?
                    AND artifact_type = 'command'
                    GROUP BY target
                    ORDER BY cnt DESC, target ASC
                    LIMIT 10
                    """,
                    (session_id,),
                ).fetchall()
            ]

        return {
            "files_read": counts.get("file_read", 0),
            "files_written": counts.get("file_write", 0),
            "files_created": counts.get("file_create", 0),
            "commands": counts.get("command", 0),
            "api_calls": counts.get("api_call", 0),
            "errors": counts.get("error", 0),
            "top_files": top_files,
            "top_commands": top_commands,
        }
