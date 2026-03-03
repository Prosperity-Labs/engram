"""SQLite-backed session store for indexing Claude Code JSONL sessions."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import vector_search


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
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL REFERENCES sessions(session_id),
    sequence            INTEGER NOT NULL,
    role                TEXT NOT NULL,
    content             TEXT,
    timestamp           TEXT,
    tool_name           TEXT,
    token_usage_in      INTEGER DEFAULT 0,
    token_usage_out     INTEGER DEFAULT 0,
    cache_read_tokens   INTEGER DEFAULT 0,
    cache_create_tokens INTEGER DEFAULT 0,
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

# ---------------------------------------------------------------------------
# Loopwright tables — worktree tracking, checkpoints, correction cycles
# ---------------------------------------------------------------------------

_LOOPWRIGHT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS worktrees (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT,
    branch_name     TEXT NOT NULL,
    base_branch     TEXT NOT NULL DEFAULT 'main',
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','passed','failed','escalated','merged')),
    task_description TEXT,
    ab_variant_label TEXT,
    ab_brief_metadata TEXT, -- JSON
    results_json     TEXT, -- JSON summary for A/B comparisons
    created_at      TEXT NOT NULL,
    resolved_at     TEXT
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    worktree_id         INTEGER NOT NULL REFERENCES worktrees(id),
    session_id          TEXT,
    git_sha             TEXT,
    test_results        TEXT,    -- JSON
    artifact_snapshot   TEXT,    -- JSON
    graph_delta         TEXT,    -- JSON (Noodlbox impact: changed symbols, callers, communities, processes)
    ab_variant_label    TEXT,
    created_at          TEXT NOT NULL,
    label               TEXT
);

CREATE TABLE IF NOT EXISTS correction_cycles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    worktree_id         INTEGER NOT NULL REFERENCES worktrees(id),
    cycle_number        INTEGER NOT NULL,
    trigger_error       TEXT,
    error_context       TEXT,    -- JSON (browser logs, DB errors, AWS logs)
    checkpoint_id       INTEGER REFERENCES checkpoints(id),
    agent_session_id    TEXT,
    outcome             TEXT CHECK(outcome IN ('passed','failed','escalated')),
    duration_seconds    INTEGER,
    created_at          TEXT NOT NULL
);

-- FTS5 for searching across worktree task descriptions and correction errors
CREATE VIRTUAL TABLE IF NOT EXISTS worktrees_fts USING fts5(
    task_description,
    branch_name,
    content='worktrees',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS worktrees_ai AFTER INSERT ON worktrees BEGIN
    INSERT INTO worktrees_fts(rowid, task_description, branch_name)
    VALUES (new.id, new.task_description, new.branch_name);
END;

CREATE TRIGGER IF NOT EXISTS worktrees_ad AFTER DELETE ON worktrees BEGIN
    INSERT INTO worktrees_fts(worktrees_fts, rowid, task_description, branch_name)
    VALUES ('delete', old.id, old.task_description, old.branch_name);
END;

CREATE TRIGGER IF NOT EXISTS worktrees_au AFTER UPDATE ON worktrees BEGIN
    INSERT INTO worktrees_fts(worktrees_fts, rowid, task_description, branch_name)
    VALUES ('delete', old.id, old.task_description, old.branch_name);
    INSERT INTO worktrees_fts(rowid, task_description, branch_name)
    VALUES (new.id, new.task_description, new.branch_name);
END;

CREATE VIRTUAL TABLE IF NOT EXISTS correction_cycles_fts USING fts5(
    trigger_error,
    content='correction_cycles',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS correction_cycles_ai AFTER INSERT ON correction_cycles BEGIN
    INSERT INTO correction_cycles_fts(rowid, trigger_error)
    VALUES (new.id, new.trigger_error);
END;

CREATE TRIGGER IF NOT EXISTS correction_cycles_ad AFTER DELETE ON correction_cycles BEGIN
    INSERT INTO correction_cycles_fts(correction_cycles_fts, rowid, trigger_error)
    VALUES ('delete', old.id, old.trigger_error);
END;

CREATE TRIGGER IF NOT EXISTS correction_cycles_au AFTER UPDATE ON correction_cycles BEGIN
    INSERT INTO correction_cycles_fts(correction_cycles_fts, rowid, trigger_error)
    VALUES ('delete', old.id, old.trigger_error);
    INSERT INTO correction_cycles_fts(rowid, trigger_error)
    VALUES (new.id, new.trigger_error);
END;

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_worktrees_session ON worktrees(session_id);
CREATE INDEX IF NOT EXISTS idx_worktrees_status ON worktrees(status);
CREATE INDEX IF NOT EXISTS idx_checkpoints_worktree ON checkpoints(worktree_id);
CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON checkpoints(session_id);
CREATE INDEX IF NOT EXISTS idx_correction_cycles_worktree ON correction_cycles(worktree_id);
CREATE INDEX IF NOT EXISTS idx_correction_cycles_checkpoint ON correction_cycles(checkpoint_id);
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
            conn.executescript(_LOOPWRIGHT_SCHEMA_SQL)
            self._migrate(conn)
            if vector_search.is_available():
                vector_search.init_vec_table(conn)

    def _migrate(self, conn) -> None:
        """Add columns that may be missing from older databases."""
        message_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()
        }
        if "cache_read_tokens" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN cache_read_tokens INTEGER DEFAULT 0")
        if "cache_create_tokens" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN cache_create_tokens INTEGER DEFAULT 0")
        if "agent_id" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN agent_id TEXT")

        worktree_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(worktrees)").fetchall()
        }
        if "ab_variant_label" not in worktree_columns:
            conn.execute("ALTER TABLE worktrees ADD COLUMN ab_variant_label TEXT")
        if "ab_brief_metadata" not in worktree_columns:
            conn.execute("ALTER TABLE worktrees ADD COLUMN ab_brief_metadata TEXT")
        if "results_json" not in worktree_columns:
            conn.execute("ALTER TABLE worktrees ADD COLUMN results_json TEXT")

        checkpoint_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(checkpoints)").fetchall()
        }
        if "ab_variant_label" not in checkpoint_columns:
            conn.execute("ALTER TABLE checkpoints ADD COLUMN ab_variant_label TEXT")

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
            if vector_search.is_available():
                try:
                    conn.execute(
                        """DELETE FROM vec_messages
                           WHERE message_id IN (
                               SELECT id FROM messages WHERE session_id = ?
                           )""",
                        (session_id,),
                    )
                except Exception:
                    pass
            conn.execute(
                "DELETE FROM messages WHERE session_id = ?", (session_id,)
            )
            new_messages: list[dict] = []
            if messages:
                conn.executemany(
                    """INSERT INTO messages
                       (session_id, sequence, role, content, timestamp,
                        tool_name, token_usage_in, token_usage_out,
                        cache_read_tokens, cache_create_tokens, agent_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                            m.get("cache_read_tokens", 0),
                            m.get("cache_create_tokens", 0),
                            m.get("agent_id"),
                        )
                        for idx, m in enumerate(messages)
                    ],
                )
                rows = conn.execute(
                    """SELECT id AS message_id, content
                       FROM messages
                       WHERE session_id = ?
                       ORDER BY sequence""",
                    (session_id,),
                ).fetchall()
                new_messages = [dict(row) for row in rows]

            if vector_search.is_available() and new_messages:
                vector_search.index_message_vectors(conn, new_messages)

        return {"session_id": session_id, "messages_indexed": len(messages)}

    def install(self) -> dict:
        """Discover and index all sessions from all available adapters.

        Returns: {"indexed": N, "skipped": N, "total_messages": N}
        """
        from ..adapters.claude_code import ClaudeCodeAdapter

        adapter = ClaudeCodeAdapter()
        session_paths = adapter.discover_sessions()

        indexed = 0
        skipped = 0
        total_messages = 0

        for filepath_str in session_paths:
            filepath = Path(filepath_str)
            session_id = filepath.stem
            if self.is_indexed(session_id):
                skipped += 1
                continue
            try:
                result = self.index_session(filepath)
                total_messages += result["messages_indexed"]
                indexed += 1
            except Exception:
                pass

        return {"indexed": indexed, "skipped": skipped, "total_messages": total_messages}

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
        project = clean_project_name(project) if project else project
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

    def clean_all_project_names(self) -> int:
        """Update all sessions with cleaned project names. Returns count updated."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT session_id, project FROM sessions WHERE project IS NOT NULL"
            ).fetchall()
            updated = 0
            for row in rows:
                cleaned = clean_project_name(row["project"])
                if cleaned != row["project"]:
                    conn.execute(
                        "UPDATE sessions SET project = ? WHERE session_id = ?",
                        (cleaned, row["session_id"]),
                    )
                    updated += 1
        return updated

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
                m.get("cache_read_tokens", 0),
                m.get("cache_create_tokens", 0),
                m.get("agent_id"),
            )
            for i, m in enumerate(messages)
        ]

        with self._connect() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO messages
                   (session_id, sequence, role, content, timestamp,
                    tool_name, token_usage_in, token_usage_out,
                    cache_read_tokens, cache_create_tokens, agent_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                m.id AS message_id,
                m.sequence,
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
                    "message_id": row["message_id"],
                    "sequence": row["sequence"],
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

    def semantic_search(self, query: str, limit: int = 20) -> list[dict]:
        """Hybrid semantic + keyword search with graceful fallback."""
        fts_results = self.search(query, limit=limit)
        if not vector_search.is_available():
            return fts_results

        with self._connect() as conn:
            return vector_search.hybrid_search(
                conn=conn,
                query=query,
                fts_results=fts_results,
                limit=limit,
            )

    def stats(self) -> dict:
        with self._connect() as conn:
            s = conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()
            m = conn.execute(
                """SELECT COUNT(*) AS c,
                          COALESCE(SUM(token_usage_in), 0)      AS ti,
                          COALESCE(SUM(token_usage_out), 0)     AS to_,
                          COALESCE(SUM(cache_read_tokens), 0)   AS cr,
                          COALESCE(SUM(cache_create_tokens), 0) AS cc
                   FROM messages"""
            ).fetchone()

        db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "total_sessions": s["c"],
            "total_messages": m["c"],
            "total_tokens_in": m["ti"],
            "total_tokens_out": m["to_"],
            "total_cache_read": m["cr"],
            "total_cache_create": m["cc"],
            "db_size_bytes": db_size,
        }

    # Opus pricing (as of Feb 2026)
    _COST_PER_M = {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.50,
        "cache_create": 18.75,
    }

    def session_costs(self, limit: int = 10) -> list[dict]:
        """Return sessions ranked by estimated cost (descending).

        Cost model: Opus pricing — $15/M input, $75/M output,
        $1.50/M cache_read, $18.75/M cache_create.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT
                       m.session_id,
                       s.project,
                       s.message_count,
                       SUM(m.token_usage_in)      AS input_tokens,
                       SUM(m.token_usage_out)     AS output_tokens,
                       SUM(m.cache_read_tokens)   AS cache_read,
                       SUM(m.cache_create_tokens) AS cache_create
                   FROM messages m
                   LEFT JOIN sessions s ON s.session_id = m.session_id
                   GROUP BY m.session_id
                   ORDER BY (
                       SUM(m.token_usage_in) * 15.0
                       + SUM(m.token_usage_out) * 75.0
                       + SUM(m.cache_read_tokens) * 1.5
                       + SUM(m.cache_create_tokens) * 18.75
                   ) DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()

        results = []
        for row in rows:
            cost = (
                row["input_tokens"] * self._COST_PER_M["input"]
                + row["output_tokens"] * self._COST_PER_M["output"]
                + row["cache_read"] * self._COST_PER_M["cache_read"]
                + row["cache_create"] * self._COST_PER_M["cache_create"]
            ) / 1_000_000
            results.append({
                "session_id": row["session_id"],
                "project": row["project"],
                "message_count": row["message_count"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cache_read_tokens": row["cache_read"],
                "cache_create_tokens": row["cache_create"],
                "estimated_cost": round(cost, 2),
            })
        return results

    def insights(self) -> dict:
        """Compute analytics across all indexed sessions.

        Returns dict with keys:
            tool_usage, role_breakdown, projects, cache_efficiency,
            hourly_activity, error_sessions, expensive_sessions, topics
        """
        with self._connect() as conn:
            # Tool usage
            tool_usage = [
                {"tool": row["tool_name"], "count": row["cnt"]}
                for row in conn.execute("""
                    SELECT tool_name, COUNT(*) as cnt
                    FROM messages
                    WHERE tool_name IS NOT NULL AND tool_name != ''
                    GROUP BY tool_name ORDER BY cnt DESC LIMIT 15
                """)
            ]

            # Role breakdown
            role_breakdown = {
                row["role"]: row["cnt"]
                for row in conn.execute("""
                    SELECT role, COUNT(*) as cnt
                    FROM messages GROUP BY role ORDER BY cnt DESC
                """)
            }

            # Projects
            projects = [
                {
                    "project": row["project"],
                    "sessions": row["cnt"],
                    "messages": row["msgs"],
                }
                for row in conn.execute("""
                    SELECT project, COUNT(*) as cnt, SUM(message_count) as msgs
                    FROM sessions WHERE project IS NOT NULL
                    GROUP BY project ORDER BY cnt DESC LIMIT 10
                """)
            ]

            # Cache efficiency
            cache_row = conn.execute("""
                SELECT
                    SUM(token_usage_in) as input,
                    SUM(cache_read_tokens) as cache_read,
                    SUM(cache_create_tokens) as cache_create,
                    SUM(token_usage_out) as output
                FROM messages
            """).fetchone()
            total_input = (
                cache_row["input"] + cache_row["cache_read"] + cache_row["cache_create"]
            )
            cost_actual = (
                cache_row["input"] * self._COST_PER_M["input"]
                + cache_row["cache_read"] * self._COST_PER_M["cache_read"]
                + cache_row["cache_create"] * self._COST_PER_M["cache_create"]
                + cache_row["output"] * self._COST_PER_M["output"]
            ) / 1_000_000
            cost_no_cache = (
                total_input * self._COST_PER_M["input"]
                + cache_row["output"] * self._COST_PER_M["output"]
            ) / 1_000_000
            cache_efficiency = {
                "total_input_tokens": total_input,
                "cache_read": cache_row["cache_read"],
                "cache_create": cache_row["cache_create"],
                "uncached_input": cache_row["input"],
                "output_tokens": cache_row["output"],
                "cache_read_pct": round(cache_row["cache_read"] / total_input * 100, 1) if total_input else 0,
                "cost_actual": round(cost_actual, 2),
                "cost_without_cache": round(cost_no_cache, 2),
                "savings": round(cost_no_cache - cost_actual, 2),
                "savings_pct": round((1 - cost_actual / cost_no_cache) * 100) if cost_no_cache else 0,
            }

            # Hourly activity
            hourly = {}
            for row in conn.execute(
                "SELECT created_at FROM sessions WHERE created_at IS NOT NULL"
            ):
                ts = row["created_at"] or ""
                if "T" in ts:
                    try:
                        h = int(ts.split("T")[1][:2])
                        hourly[h] = hourly.get(h, 0) + 1
                    except (ValueError, IndexError):
                        pass

            # Error-heavy sessions
            error_sessions = [
                {
                    "session_id": row["session_id"],
                    "project": row["project"],
                    "error_messages": row["err"],
                    "total_messages": row["message_count"],
                    "error_pct": round(row["err"] / row["message_count"] * 100) if row["message_count"] else 0,
                }
                for row in conn.execute("""
                    SELECT m.session_id, s.project, COUNT(*) as err, s.message_count
                    FROM messages m
                    JOIN sessions s ON s.session_id = m.session_id
                    WHERE (m.content LIKE '%error%' OR m.content LIKE '%Error%'
                           OR m.content LIKE '%FAIL%' OR m.content LIKE '%failed%')
                    AND m.role = 'assistant'
                    GROUP BY m.session_id ORDER BY COUNT(*) DESC LIMIT 10
                """)
            ]

            # Most expensive per-message
            expensive = [
                {
                    "session_id": row["sid"],
                    "project": row["project"],
                    "messages": row["mc"],
                    "total_cost": round(
                        (row["ti"] * 15 + row["cr"] * 1.5 + row["cc"] * 18.75 + row["to_"] * 75) / 1e6, 2
                    ),
                    "cost_per_msg": round(
                        (row["ti"] * 15 + row["cr"] * 1.5 + row["cc"] * 18.75 + row["to_"] * 75) / 1e6 / row["mc"], 3
                    ),
                }
                for row in conn.execute("""
                    SELECT s.session_id as sid, s.project, s.message_count as mc,
                           SUM(m.token_usage_in) as ti, SUM(m.cache_read_tokens) as cr,
                           SUM(m.cache_create_tokens) as cc, SUM(m.token_usage_out) as to_
                    FROM sessions s JOIN messages m ON m.session_id = s.session_id
                    WHERE s.message_count > 20
                    GROUP BY s.session_id
                    ORDER BY (SUM(m.token_usage_in)*15.0 + SUM(m.cache_read_tokens)*1.5
                             + SUM(m.cache_create_tokens)*18.75 + SUM(m.token_usage_out)*75.0)
                             / s.message_count DESC
                    LIMIT 10
                """)
            ]

            # Topic frequency
            topic_keywords = [
                "webhook", "deploy", "migration", "KYB", "KYC", "withdraw",
                "deposit", "balance", "wallet", "docker", "database", "test", "bug", "fix",
            ]
            topics = {}
            for kw in topic_keywords:
                row = conn.execute(
                    "SELECT COUNT(DISTINCT session_id) as c FROM messages WHERE content LIKE ?",
                    (f"%{kw}%",),
                ).fetchone()
                topics[kw] = row["c"]

        return {
            "tool_usage": tool_usage,
            "role_breakdown": role_breakdown,
            "projects": projects,
            "cache_efficiency": cache_efficiency,
            "hourly_activity": hourly,
            "error_sessions": error_sessions,
            "expensive_sessions": expensive,
            "topics": topics,
        }

    # ------------------------------------------------------------------
    # Loopwright: worktree / checkpoint / correction cycle helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_worktree(
        self,
        branch_name: str,
        *,
        session_id: str | None = None,
        base_branch: str = "main",
        status: str = "active",
        task_description: str | None = None,
    ) -> int:
        """Insert a new worktree row. Returns the new worktree id."""
        now = self._now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO worktrees
                   (session_id, branch_name, base_branch, status,
                    task_description, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session_id, branch_name, base_branch, status,
                 task_description, now),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def create_checkpoint(
        self,
        worktree_id: int,
        *,
        session_id: str | None = None,
        git_sha: str | None = None,
        test_results: Any = None,
        artifact_snapshot: Any = None,
        graph_delta: Any = None,
        ab_variant_label: str | None = None,
        label: str | None = None,
    ) -> int:
        """Insert a checkpoint for a worktree. Returns the new checkpoint id."""
        now = self._now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO checkpoints
                   (worktree_id, session_id, git_sha, test_results,
                    artifact_snapshot, graph_delta, ab_variant_label, created_at, label)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    worktree_id,
                    session_id,
                    git_sha,
                    json.dumps(test_results) if test_results is not None else None,
                    json.dumps(artifact_snapshot) if artifact_snapshot is not None else None,
                    json.dumps(graph_delta) if graph_delta is not None else None,
                    ab_variant_label,
                    now,
                    label,
                ),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def create_correction_cycle(
        self,
        worktree_id: int,
        cycle_number: int,
        *,
        trigger_error: str | None = None,
        error_context: Any = None,
        checkpoint_id: int | None = None,
        agent_session_id: str | None = None,
        outcome: str | None = None,
        duration_seconds: int | None = None,
    ) -> int:
        """Insert a correction cycle. Returns the new cycle id."""
        now = self._now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO correction_cycles
                   (worktree_id, cycle_number, trigger_error, error_context,
                    checkpoint_id, agent_session_id, outcome,
                    duration_seconds, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    worktree_id,
                    cycle_number,
                    trigger_error,
                    json.dumps(error_context) if error_context is not None else None,
                    checkpoint_id,
                    agent_session_id,
                    outcome,
                    duration_seconds,
                    now,
                ),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def get_latest_checkpoint(self, worktree_id: int) -> dict | None:
        """Return the most recent checkpoint for a worktree, or None."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM checkpoints
                   WHERE worktree_id = ?
                   ORDER BY id DESC LIMIT 1""",
                (worktree_id,),
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            for json_col in ("test_results", "artifact_snapshot", "graph_delta"):
                if d.get(json_col):
                    try:
                        d[json_col] = json.loads(d[json_col])
                    except (json.JSONDecodeError, TypeError):
                        pass
            return d

    def get_worktree(self, worktree_id: int) -> dict | None:
        """Return a worktree by id, or None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM worktrees WHERE id = ?", (worktree_id,)
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            for json_col in ("ab_brief_metadata", "results_json"):
                if d.get(json_col):
                    try:
                        d[json_col] = json.loads(d[json_col])
                    except (json.JSONDecodeError, TypeError):
                        pass
            return d

    def update_worktree_status(
        self, worktree_id: int, status: str
    ) -> None:
        """Update worktree status. Sets resolved_at on terminal states."""
        resolved = self._now_iso() if status in ("passed", "failed", "escalated", "merged") else None
        with self._connect() as conn:
            conn.execute(
                """UPDATE worktrees SET status = ?, resolved_at = COALESCE(?, resolved_at)
                   WHERE id = ?""",
                (status, resolved, worktree_id),
            )

    def update_worktree_ab_metadata(
        self,
        worktree_id: int,
        *,
        variant_label: str | None = None,
        brief_metadata: Any = None,
    ) -> None:
        """Persist A/B brief metadata on a worktree row."""
        with self._connect() as conn:
            conn.execute(
                """UPDATE worktrees
                   SET ab_variant_label = COALESCE(?, ab_variant_label),
                       ab_brief_metadata = COALESCE(?, ab_brief_metadata)
                   WHERE id = ?""",
                (
                    variant_label,
                    json.dumps(brief_metadata) if brief_metadata is not None else None,
                    worktree_id,
                ),
            )

    def store_worktree_results(self, worktree_id: int, results: Any) -> None:
        """Persist computed A/B result summary JSON on a worktree row."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE worktrees SET results_json = ? WHERE id = ?",
                (json.dumps(results), worktree_id),
            )

    def get_worktree_results(self, worktree_id: int) -> dict | None:
        """Return parsed worktree results_json, if present."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT results_json FROM worktrees WHERE id = ?",
                (worktree_id,),
            ).fetchone()
        if not row or not row["results_json"]:
            return None
        try:
            parsed = json.loads(row["results_json"])
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def get_correction_cycles(self, worktree_id: int) -> list[dict]:
        """Return all correction cycles for a worktree, ordered by cycle number."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM correction_cycles
                   WHERE worktree_id = ?
                   ORDER BY cycle_number""",
                (worktree_id,),
            ).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                if d.get("error_context"):
                    try:
                        d["error_context"] = json.loads(d["error_context"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                results.append(d)
            return results

    def get_correction_cycle_count(self, worktree_id: int) -> int:
        """Return number of correction cycles for a worktree."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM correction_cycles WHERE worktree_id = ?",
                (worktree_id,),
            ).fetchone()
            return row["cnt"] if row else 0

    def get_latest_correction_cycle(self, worktree_id: int) -> dict | None:
        """Return the most recent correction cycle, or None."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM correction_cycles
                   WHERE worktree_id = ?
                   ORDER BY cycle_number DESC LIMIT 1""",
                (worktree_id,),
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            if d.get("error_context"):
                try:
                    d["error_context"] = json.loads(d["error_context"])
                except (json.JSONDecodeError, TypeError):
                    pass
            return d

    def list_worktrees_by_status(self, status: str, limit: int = 50) -> list[dict]:
        """List worktrees filtered by status."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM worktrees
                   WHERE status = ?
                   ORDER BY id DESC
                   LIMIT ?""",
                (status, limit),
            ).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                for json_col in ("ab_brief_metadata", "results_json"):
                    if d.get(json_col):
                        try:
                            d[json_col] = json.loads(d[json_col])
                        except (json.JSONDecodeError, TypeError):
                            pass
                results.append(d)
            return results

    def get_worktree_with_cycles(self, worktree_id: int) -> dict | None:
        """Return worktree with its correction_cycles and latest checkpoint embedded."""
        wt = self.get_worktree(worktree_id)
        if wt is None:
            return None
        wt["correction_cycles"] = self.get_correction_cycles(worktree_id)
        wt["latest_checkpoint"] = self.get_latest_checkpoint(worktree_id)
        return wt

    def search_worktrees(self, query: str, limit: int = 20) -> list[dict]:
        """Full-text search across worktree task descriptions and branch names."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT w.*,
                       snippet(worktrees_fts, 0, '>>>', '<<<', '...', 48) AS snippet
                   FROM worktrees_fts
                   JOIN worktrees w ON w.id = worktrees_fts.rowid
                   WHERE worktrees_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def search_correction_errors(self, query: str, limit: int = 20) -> list[dict]:
        """Full-text search across correction cycle trigger errors."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT cc.*,
                       snippet(correction_cycles_fts, 0, '>>>', '<<<', '...', 48) AS snippet
                   FROM correction_cycles_fts
                   JOIN correction_cycles cc ON cc.id = correction_cycles_fts.rowid
                   WHERE correction_cycles_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, limit),
            ).fetchall()
            return [dict(r) for r in rows]

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

_PROJECT_BASE_MARKERS = {"development", "desktop", "projects", "plugins", "marketplaces",
                         "worktrees"}


def clean_project_name(raw: str) -> str:
    """Normalize raw Claude project path tokens into readable project names.

    Claude encodes project dirs by replacing ``/`` and ``.`` with ``-``.
    We strip the home-directory prefix (up to the last known base-dir
    marker like "development") and then try to recover the original
    ``parent/child`` structure by probing the filesystem.

    When the filesystem is unavailable (e.g. different machine), the
    function still strips the prefix and returns the flat hyphenated name
    which is always an improvement over the raw encoded path.

    Examples::

        "-home-user-Desktop-development-monra-app"            -> "monra-app"
        "-home-user-Desktop-development-monra-app-monra-core" -> "monra-app/monra-core"  (if dir exists)
        "-home-user-Desktop-development-monra-app-monra-core" -> "monra-app-monra-core"  (if no filesystem)
        "-home-user-Desktop-development-music-nft-platform"   -> "music-nft-platform"
        "-home-user-Desktop-development"                      -> "development"
        "app"                                                  -> "app"
    """
    if not raw:
        return raw

    if not raw.startswith("-home-") and not raw.startswith("-"):
        return raw

    parts = [part for part in raw.strip("-").split("-") if part]
    if not parts:
        return raw

    # Find last base-directory marker
    marker_idx = None
    for idx, part in enumerate(parts):
        if part.lower() in _PROJECT_BASE_MARKERS:
            marker_idx = idx

    if marker_idx is None:
        return raw

    remainder = parts[marker_idx + 1:]
    if not remainder:
        return parts[marker_idx]

    # Reconstruct the path segment after the marker.  Try to find the
    # longest prefix that matches an actual directory on disk so we can
    # split ``monra-app-monra-core`` into ``monra-app/monra-core``.
    flat = "-".join(remainder)

    # Build the parent directory from everything up to and including the
    # marker (e.g. /home/prosperitylabs/Desktop/development).
    parent = Path("/") / "/".join(parts[: marker_idx + 1])

    if parent.is_dir():
        # Greedily match the longest directory name.
        # Claude also encodes dots as hyphens (monra.app -> monra-app),
        # so try both the hyphenated name and dot variants.
        for length in range(len(remainder), 0, -1):
            candidate = "-".join(remainder[:length])
            candidates = [candidate, candidate.replace("-", "."), candidate.replace("-", ".", 1)]
            for name in candidates:
                if (parent / name).is_dir():
                    rest = remainder[length:]
                    if rest:
                        return f"{candidate}/{'-'.join(rest)}"
                    return candidate
                    break

    # Filesystem unavailable or no match — return flat
    return flat


def _guess_project(filepath: Path) -> str | None:
    """Derive project name from the standard Claude session path layout."""
    # ~/.claude/projects/<project-dir>/<session-id>.jsonl
    parts = filepath.parts
    try:
        idx = parts.index("projects")
        if idx + 1 < len(parts) - 1:
            return clean_project_name(parts[idx + 1])
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
