"""SQLite-backed session store for indexing Claude Code JSONL sessions."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any


_DEFAULT_DB_PATH = Path.home() / ".config" / "engram" / "sessions.db"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    filepath        TEXT NOT NULL,
    project         TEXT,
    message_count   INTEGER DEFAULT 0,
    file_size_bytes INTEGER DEFAULT 0,
    created_at      TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(session_id),
    sequence        INTEGER NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT,
    timestamp       TEXT,
    tool_name       TEXT,
    token_usage_in  INTEGER DEFAULT 0,
    token_usage_out INTEGER DEFAULT 0,
    UNIQUE(session_id, sequence)
);

-- FTS5 virtual table for full-text search across message content
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    role,
    tool_name,
    content='messages',
    content_rowid='id',
    tokenize='porter unicode61'
);

-- Triggers to keep FTS index in sync with messages table
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content, role, tool_name)
    VALUES (new.id, new.content, new.role, new.tool_name);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, role, tool_name)
    VALUES ('delete', old.id, old.content, old.role, old.tool_name);
END;

CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, role, tool_name)
    VALUES ('delete', old.id, old.content, old.role, old.tool_name);
    INSERT INTO messages_fts(rowid, content, role, tool_name)
    VALUES (new.id, new.content, new.role, new.tool_name);
END;
"""


class SessionDB:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA_SQL)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_session(self, filepath: Path) -> dict:
        """Parse a JSONL session file via ClaudeCodeAdapter, store session + messages."""
        from ..adapters.claude_code import ClaudeCodeAdapter

        filepath = Path(filepath)
        adapter = ClaudeCodeAdapter()
        session = adapter.parse_file(str(filepath))
        return self.index_from_session(session, filepath)

    def index_from_session(self, session, filepath: Path | None = None) -> dict:
        """Index an EngramSession into the database.

        Works with any adapter's output — agent-agnostic.
        """
        from ..adapters.base import EngramSession

        session_id = session.session_id
        project = session.project
        messages = session.to_message_dicts()

        if filepath is None and session.filepath:
            filepath = Path(session.filepath)

        file_size = 0
        if filepath:
            filepath = Path(filepath)
            try:
                file_size = filepath.stat().st_size
            except OSError:
                pass

        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sessions
                   (session_id, filepath, project, message_count,
                    file_size_bytes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    str(filepath) if filepath else "",
                    project,
                    len(messages),
                    file_size,
                    session.start_time,
                    session.end_time,
                ),
            )
            conn.execute(
                "DELETE FROM messages WHERE session_id = ?", (session_id,)
            )
            if messages:
                conn.executemany(
                    """INSERT INTO messages
                       (session_id, sequence, role, content, timestamp,
                        tool_name, token_usage_in, token_usage_out)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            session_id,
                            idx,
                            m["role"],
                            m.get("content"),
                            m.get("timestamp"),
                            m.get("tool_name"),
                            m.get("token_usage_in", 0),
                            m.get("token_usage_out", 0),
                        )
                        for idx, m in enumerate(messages)
                    ],
                )

        return {"session_id": session_id, "messages_indexed": len(messages)}

    def is_indexed(self, session_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT message_count FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return row is not None and row["message_count"] > 0

    def get_last_sequence(self, session_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(sequence) AS mx FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            val = row["mx"] if row else None
            return val if val is not None else 0

    def upsert_session_meta(
        self, session_id: str, filepath: str, project: str | None = None
    ) -> None:
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT message_count FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            msg_count = existing["message_count"] if existing else 0

            conn.execute(
                """INSERT OR REPLACE INTO sessions
                   (session_id, filepath, project, message_count)
                   VALUES (?, ?, ?, ?)""",
                (session_id, filepath, project, msg_count),
            )

    def insert_messages(
        self,
        session_id: str,
        messages: list[dict],
        start_seq: int | None = None,
    ) -> int:
        if not messages:
            return 0

        if start_seq is None:
            start_seq = self.get_last_sequence(session_id) + 1

        rows = [
            (
                session_id,
                start_seq + i,
                m["role"],
                m.get("content"),
                m.get("timestamp"),
                m.get("tool_name"),
                m.get("token_usage_in", 0),
                m.get("token_usage_out", 0),
            )
            for i, m in enumerate(messages)
        ]

        with self._connect() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO messages
                   (session_id, sequence, role, content, timestamp,
                    tool_name, token_usage_in, token_usage_out)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            conn.execute(
                """UPDATE sessions
                   SET message_count = (
                       SELECT COUNT(*) FROM messages WHERE session_id = ?
                   )
                   WHERE session_id = ?""",
                (session_id, session_id),
            )

        return len(rows)

    def search(
        self,
        query: str,
        limit: int = 20,
        role: str | None = None,
        session_id: str | None = None,
    ) -> list[dict]:
        """Full-text search across all indexed messages.

        Args:
            query: FTS5 query (supports AND, OR, NOT, "phrases", prefix*)
            limit: Max results to return
            role: Filter by role (user, assistant, summary)
            session_id: Filter to a specific session

        Returns list of dicts with: session_id, project, role, tool_name,
            content (snippet with highlights), timestamp, rank
        """
        conditions = ["messages_fts MATCH ?"]
        params: list = [query]

        if role:
            conditions.append("m.role = ?")
            params.append(role)
        if session_id:
            conditions.append("m.session_id = ?")
            params.append(session_id)

        where = " AND ".join(conditions)
        params.append(limit)

        sql = f"""
            SELECT
                m.session_id,
                s.project,
                m.role,
                m.tool_name,
                snippet(messages_fts, 0, '>>>', '<<<', '...', 48) AS snippet,
                m.content,
                m.timestamp,
                rank
            FROM messages_fts
            JOIN messages m ON m.id = messages_fts.rowid
            LEFT JOIN sessions s ON s.session_id = m.session_id
            WHERE {where}
            ORDER BY rank
            LIMIT ?
        """

        results = []
        with self._connect() as conn:
            for row in conn.execute(sql, params):
                results.append({
                    "session_id": row["session_id"],
                    "project": row["project"],
                    "role": row["role"],
                    "tool_name": row["tool_name"],
                    "snippet": row["snippet"],
                    "content": row["content"],
                    "timestamp": row["timestamp"],
                    "rank": row["rank"],
                })
        return results

    def stats(self) -> dict:
        with self._connect() as conn:
            s = conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()
            m = conn.execute(
                """SELECT COUNT(*) AS c,
                          COALESCE(SUM(token_usage_in), 0)  AS ti,
                          COALESCE(SUM(token_usage_out), 0) AS to_
                   FROM messages"""
            ).fetchone()

        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "total_sessions": s["c"],
            "total_messages": m["c"],
            "total_tokens_in": m["ti"],
            "total_tokens_out": m["to_"],
            "db_size_bytes": db_size,
        }

    # ------------------------------------------------------------------
    # JSONL parsing
    # ------------------------------------------------------------------

    def _extract_messages(self, filepath: Path) -> list[dict]:
        """Parse a Claude Code JSONL session file into a flat message list."""
        results: list[dict] = []
        with open(filepath, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type")
                ts = entry.get("timestamp")
                message = entry.get("message", {})
                content_blocks = message.get("content", [])
                usage = message.get("usage", {})
                tokens_in = usage.get("input_tokens", 0)
                tokens_out = usage.get("output_tokens", 0)

                if entry_type == "user":
                    text = _collect_user_text(content_blocks)
                    results.append({
                        "role": "user",
                        "content": text,
                        "timestamp": ts,
                        "tool_name": None,
                        "token_usage_in": tokens_in,
                        "token_usage_out": tokens_out,
                    })

                elif entry_type == "assistant":
                    if isinstance(content_blocks, str):
                        results.append({
                            "role": "assistant",
                            "content": content_blocks,
                            "timestamp": ts,
                            "tool_name": None,
                            "token_usage_in": tokens_in,
                            "token_usage_out": tokens_out,
                        })
                        continue

                    for block in content_blocks:
                        if isinstance(block, str):
                            results.append({
                                "role": "assistant",
                                "content": block,
                                "timestamp": ts,
                                "tool_name": None,
                                "token_usage_in": tokens_in,
                                "token_usage_out": tokens_out,
                            })
                            # Only attribute token usage to the first block
                            tokens_in, tokens_out = 0, 0
                            continue

                        btype = block.get("type")
                        if btype == "text":
                            results.append({
                                "role": "assistant",
                                "content": block.get("text", ""),
                                "timestamp": ts,
                                "tool_name": None,
                                "token_usage_in": tokens_in,
                                "token_usage_out": tokens_out,
                            })
                        elif btype == "tool_use":
                            summary = _tool_use_summary(block)
                            results.append({
                                "role": "assistant",
                                "content": summary,
                                "timestamp": ts,
                                "tool_name": block.get("name"),
                                "token_usage_in": tokens_in,
                                "token_usage_out": tokens_out,
                            })
                        elif btype == "thinking":
                            thinking = (block.get("thinking") or "")[:500]
                            results.append({
                                "role": "assistant",
                                "content": thinking,
                                "timestamp": ts,
                                "tool_name": None,
                                "token_usage_in": tokens_in,
                                "token_usage_out": tokens_out,
                            })

                        tokens_in, tokens_out = 0, 0

                elif entry_type == "summary":
                    text = _collect_user_text(content_blocks) if content_blocks else ""
                    if not text and isinstance(message.get("content"), str):
                        text = message["content"]
                    results.append({
                        "role": "summary",
                        "content": text,
                        "timestamp": ts,
                        "tool_name": None,
                        "token_usage_in": tokens_in,
                        "token_usage_out": tokens_out,
                    })

        return results


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _guess_project(filepath: Path) -> str | None:
    """Derive project name from the standard Claude session path layout."""
    # ~/.claude/projects/<project-dir>/<session-id>.jsonl
    parts = filepath.parts
    try:
        idx = parts.index("projects")
        if idx + 1 < len(parts) - 1:
            return parts[idx + 1]
    except ValueError:
        pass
    return None


def _collect_user_text(blocks: Any) -> str:
    """Concatenate text from user content blocks."""
    if isinstance(blocks, str):
        return blocks
    pieces: list[str] = []
    for block in blocks:
        if isinstance(block, str):
            pieces.append(block)
        elif isinstance(block, dict):
            if block.get("type") == "text":
                pieces.append(block.get("text", ""))
            elif block.get("type") == "tool_result":
                # tool_result content may be a list of blocks or a string
                inner = block.get("content", "")
                if isinstance(inner, list):
                    for sub in inner:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            pieces.append(sub.get("text", ""))
                        elif isinstance(sub, str):
                            pieces.append(sub)
                elif isinstance(inner, str):
                    pieces.append(inner)
    return "\n".join(pieces)


def _tool_use_summary(block: dict) -> str:
    """Build a short string summarising a tool_use block."""
    name = block.get("name", "unknown_tool")
    inp = block.get("input", {})
    if isinstance(inp, dict):
        keys = list(inp.keys())[:4]
        preview = ", ".join(f"{k}=…" for k in keys)
        return f"tool_use:{name}({preview})"
    return f"tool_use:{name}()"
