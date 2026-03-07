"""Load Engram SQLite data into Memgraph knowledge graph.

All operations are idempotent (MERGE-based) and batched.
SQLite is opened read-only (?mode=ro).
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from neo4j import Driver


# Cost model (Opus pricing, matches session_db.py)
_COST_PER_M = {
    "input": 15.0,
    "output": 75.0,
    "cache_read": 1.50,
    "cache_create": 18.75,
}

# Concept keywords to scan for in user messages
_CONCEPT_KEYWORDS = [
    "authentication", "authorization", "database", "deployment", "docker",
    "testing", "api", "webhook", "migration", "caching", "logging",
    "monitoring", "security", "performance", "refactoring", "ci/cd",
    "frontend", "backend", "infrastructure", "configuration",
]

_CONCEPT_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _CONCEPT_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# Test file patterns
_TEST_PATTERNS = re.compile(
    r"(^|/)test_|\.test\.|\.spec\.|/tests/|/__tests__/", re.IGNORECASE
)

BATCH_SIZE = 500


class GraphLoader:
    """Reads Engram SQLite DB and populates Memgraph."""

    def __init__(self, driver: Driver, db_path: str | Path | None = None):
        self.driver = driver
        if db_path is None:
            db_path = Path.home() / ".config" / "engram" / "sessions.db"
        self.db_path = str(db_path)

    def _sqlite_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _project_filter(self, project: str | None) -> tuple[str, list]:
        """Return SQL WHERE clause and params for optional project filter."""
        if project:
            return "AND s.project = ?", [project]
        return "", []

    def _run_batched(self, cypher: str, rows: list[dict], batch_size: int = BATCH_SIZE) -> int:
        """Execute Cypher UNWIND in batches."""
        total = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            with self.driver.session() as session:
                session.run(cypher, rows=batch)
            total += len(batch)
        return total

    # ── Schema ───────────────────────────────────────────────────────

    def ensure_schema(self) -> None:
        """Create constraints and indexes (idempotent)."""
        schema_path = Path(__file__).parent / "schema.cypher"
        statements = [
            s.strip()
            for s in schema_path.read_text().split(";")
            if s.strip() and not s.strip().startswith("//")
        ]
        with self.driver.session() as session:
            for stmt in statements:
                try:
                    session.run(stmt)
                except Exception:
                    # Constraint/index already exists — safe to ignore
                    pass

    # ── File Nodes ───────────────────────────────────────────────────

    def load_file_nodes(self, project: str | None = None) -> int:
        """Load File nodes from artifact data."""
        proj_clause, proj_params = self._project_filter(project)
        sql = f"""
            SELECT
                a.target AS path,
                s.project,
                SUM(CASE WHEN a.artifact_type = 'file_read' THEN 1 ELSE 0 END) AS read_count,
                SUM(CASE WHEN a.artifact_type IN ('file_write', 'file_create') THEN 1 ELSE 0 END) AS write_count,
                MAX(s.updated_at) AS last_seen
            FROM artifacts a
            JOIN sessions s ON s.session_id = a.session_id
            WHERE a.artifact_type IN ('file_read', 'file_write', 'file_create')
              AND a.target NOT LIKE '%*%'
              AND a.target NOT LIKE 'tool_use:%'
              {proj_clause}
            GROUP BY a.target, s.project
        """
        conn = self._sqlite_conn()
        try:
            rows = [dict(r) for r in conn.execute(sql, proj_params).fetchall()]
        finally:
            conn.close()

        if not rows:
            return 0

        # Extract filename from path
        for r in rows:
            parts = r["path"].rsplit("/", 1)
            r["name"] = parts[-1] if len(parts) > 1 else r["path"]

        cypher = """
            UNWIND $rows AS r
            MERGE (f:File {path: r.path})
            SET f.name = r.name,
                f.project = r.project,
                f.read_count = r.read_count,
                f.write_count = r.write_count,
                f.last_seen = r.last_seen
        """
        return self._run_batched(cypher, rows)

    # ── Session Nodes ────────────────────────────────────────────────

    def load_session_nodes(self, project: str | None = None) -> int:
        """Load Session nodes and TOUCHED edges to Files."""
        proj_clause, proj_params = self._project_filter(project)

        # Session metadata with token aggregates
        sql_sessions = f"""
            SELECT
                s.session_id AS id,
                s.project,
                s.message_count,
                s.created_at,
                s.updated_at,
                COALESCE(SUM(m.token_usage_in), 0) AS tokens_in,
                COALESCE(SUM(m.token_usage_out), 0) AS tokens_out,
                COALESCE(SUM(m.cache_read_tokens), 0) AS cache_read,
                COALESCE(SUM(m.cache_create_tokens), 0) AS cache_create
            FROM sessions s
            LEFT JOIN messages m ON m.session_id = s.session_id
            WHERE 1=1 {proj_clause}
            GROUP BY s.session_id
        """
        conn = self._sqlite_conn()
        try:
            session_rows = [dict(r) for r in conn.execute(sql_sessions, proj_params).fetchall()]
        finally:
            conn.close()

        if not session_rows:
            return 0

        # Compute derived fields
        for r in session_rows:
            cost = (
                r["tokens_in"] * _COST_PER_M["input"]
                + r["tokens_out"] * _COST_PER_M["output"]
                + r["cache_read"] * _COST_PER_M["cache_read"]
                + r["cache_create"] * _COST_PER_M["cache_create"]
            ) / 1_000_000
            r["cost"] = round(cost, 4)

            # Duration in minutes from created_at to updated_at
            r["duration"] = None
            if r["created_at"] and r["updated_at"]:
                try:
                    from datetime import datetime
                    fmt = "%Y-%m-%dT%H:%M:%S" if "T" in (r["created_at"] or "") else "%Y-%m-%d %H:%M:%S"
                    t0 = datetime.fromisoformat(r["created_at"].split(".")[0])
                    t1 = datetime.fromisoformat(r["updated_at"].split(".")[0])
                    r["duration"] = round((t1 - t0).total_seconds() / 60, 1)
                except (ValueError, TypeError):
                    pass

        cypher_sessions = """
            UNWIND $rows AS r
            MERGE (s:Session {id: r.id})
            SET s.project = r.project,
                s.message_count = r.message_count,
                s.cost = r.cost,
                s.duration = r.duration,
                s.created_at = r.created_at,
                s.updated_at = r.updated_at,
                s.tokens_in = r.tokens_in,
                s.tokens_out = r.tokens_out
        """
        count = self._run_batched(cypher_sessions, session_rows)

        # TOUCHED edges: session -> file with read/write counts
        proj_clause2, proj_params2 = self._project_filter(project)
        sql_touched = f"""
            SELECT
                a.session_id,
                a.target AS path,
                SUM(CASE WHEN a.artifact_type = 'file_read' THEN 1 ELSE 0 END) AS read_count,
                SUM(CASE WHEN a.artifact_type IN ('file_write', 'file_create') THEN 1 ELSE 0 END) AS write_count
            FROM artifacts a
            JOIN sessions s ON s.session_id = a.session_id
            WHERE a.artifact_type IN ('file_read', 'file_write', 'file_create')
              AND a.target NOT LIKE '%*%'
              AND a.target NOT LIKE 'tool_use:%'
              {proj_clause2}
            GROUP BY a.session_id, a.target
        """
        conn = self._sqlite_conn()
        try:
            touched_rows = [dict(r) for r in conn.execute(sql_touched, proj_params2).fetchall()]
        finally:
            conn.close()

        if touched_rows:
            cypher_touched = """
                UNWIND $rows AS r
                MATCH (s:Session {id: r.session_id})
                MATCH (f:File {path: r.path})
                MERGE (s)-[t:TOUCHED]->(f)
                SET t.read_count = r.read_count,
                    t.write_count = r.write_count
            """
            self._run_batched(cypher_touched, touched_rows)

        return count

    # ── Co-Change Edges ──────────────────────────────────────────────

    def load_co_change_edges(self, project: str | None = None) -> int:
        """Load CO_CHANGES_WITH edges between files modified in same sessions."""
        proj_clause, proj_params = self._project_filter(project)
        sql = f"""
            SELECT
                a1.target AS file_a,
                a2.target AS file_b,
                COUNT(DISTINCT a1.session_id) AS co_sessions,
                MAX(s.updated_at) AS last_seen
            FROM artifacts a1
            JOIN artifacts a2 ON a1.session_id = a2.session_id AND a1.target < a2.target
            JOIN sessions s ON s.session_id = a1.session_id
            WHERE a1.artifact_type IN ('file_write', 'file_create')
              AND a2.artifact_type IN ('file_write', 'file_create')
              AND a1.target NOT LIKE '%*%'
              AND a2.target NOT LIKE '%*%'
              AND a1.target NOT LIKE 'tool_use:%'
              AND a2.target NOT LIKE 'tool_use:%'
              {proj_clause}
            GROUP BY a1.target, a2.target
            HAVING co_sessions >= 2
        """
        conn = self._sqlite_conn()
        try:
            rows = [dict(r) for r in conn.execute(sql, proj_params).fetchall()]
        finally:
            conn.close()

        if not rows:
            return 0

        cypher = """
            UNWIND $rows AS r
            MATCH (f1:File {path: r.file_a})
            MATCH (f2:File {path: r.file_b})
            MERGE (f1)-[e:CO_CHANGES_WITH]->(f2)
            SET e.count = r.co_sessions,
                e.last_seen = r.last_seen
        """
        return self._run_batched(cypher, rows)

    # ── Error Nodes ──────────────────────────────────────────────────

    def load_error_nodes(self, project: str | None = None) -> int:
        """Load Error nodes and CAUSES_ERROR edges using sequence proximity."""
        proj_clause, proj_params = self._project_filter(project)

        # Group errors by pattern (first 100 chars)
        sql_errors = f"""
            SELECT
                SUBSTR(a.target, 1, 100) AS pattern,
                MIN(a.target) AS message,
                COUNT(*) AS frequency,
                MIN(s.created_at) AS first_seen,
                MAX(s.updated_at) AS last_seen
            FROM artifacts a
            JOIN sessions s ON s.session_id = a.session_id
            WHERE a.artifact_type = 'error'
              {proj_clause}
            GROUP BY SUBSTR(a.target, 1, 100)
        """
        conn = self._sqlite_conn()
        try:
            error_rows = [dict(r) for r in conn.execute(sql_errors, proj_params).fetchall()]
        finally:
            conn.close()

        if not error_rows:
            return 0

        cypher_errors = """
            UNWIND $rows AS r
            MERGE (e:Error {pattern: r.pattern})
            SET e.message = r.message,
                e.frequency = r.frequency,
                e.first_seen = r.first_seen,
                e.last_seen = r.last_seen
        """
        count = self._run_batched(cypher_errors, error_rows)

        # CAUSES_ERROR edges: files written within ±10 sequence of an error
        sql_causes = f"""
            SELECT
                w.target AS file_path,
                SUBSTR(e.target, 1, 100) AS error_pattern,
                COUNT(*) AS occurrences,
                CAST(COUNT(*) AS FLOAT) / MAX(
                    (SELECT COUNT(*) FROM artifacts w2
                     WHERE w2.target = w.target
                       AND w2.artifact_type IN ('file_write', 'file_create')),
                    1
                ) AS ratio
            FROM artifacts w
            JOIN artifacts e ON e.session_id = w.session_id
                             AND e.artifact_type = 'error'
                             AND ABS(e.sequence - w.sequence) <= 10
            JOIN sessions s ON s.session_id = w.session_id
            WHERE w.artifact_type IN ('file_write', 'file_create')
              AND w.target NOT LIKE '%*%'
              AND w.target NOT LIKE 'tool_use:%'
              {proj_clause}
            GROUP BY w.target, SUBSTR(e.target, 1, 100)
        """
        conn = self._sqlite_conn()
        try:
            causes_rows = [dict(r) for r in conn.execute(sql_causes, proj_params).fetchall()]
        finally:
            conn.close()

        if causes_rows:
            cypher_causes = """
                UNWIND $rows AS r
                MATCH (f:File {path: r.file_path})
                MATCH (e:Error {pattern: r.error_pattern})
                MERGE (f)-[c:CAUSES_ERROR]->(e)
                SET c.count = r.occurrences,
                    c.ratio = r.ratio
            """
            self._run_batched(cypher_causes, causes_rows)

        # Update danger_ratio on File nodes
        cypher_danger = """
            MATCH (f:File)-[c:CAUSES_ERROR]->(:Error)
            WITH f, SUM(c.count) AS total_errors
            SET f.danger_ratio = toFloat(total_errors) / CASE WHEN f.write_count > 0 THEN f.write_count ELSE 1 END
        """
        with self.driver.session() as session:
            session.run(cypher_danger)

        return count

    # ── TESTED_BY Edges ──────────────────────────────────────────────

    def load_tested_by_edges(self, project: str | None = None) -> int:
        """Infer TESTED_BY edges from co-change patterns with test files."""
        # Memgraph regex: match test file patterns
        test_pattern = ".*(test_|_test\\.|\\.test\\.|\\.spec\\.|/tests/|/__tests__/).*"
        cypher = """
            MATCH (f1:File)-[:CO_CHANGES_WITH]-(f2:File)
            WHERE f1.path <> f2.path
              AND f1.path =~ $pattern
              AND NOT f2.path =~ $pattern
            MERGE (f2)-[:TESTED_BY]->(f1)
        """
        with self.driver.session() as session:
            result = session.run(cypher, pattern=test_pattern)
            summary = result.consume()
        return summary.counters.relationships_created

    # ── Concept Nodes ────────────────────────────────────────────────

    def load_concept_nodes(self, project: str | None = None) -> int:
        """Extract concepts from user messages and link to files touched in those sessions."""
        proj_clause, proj_params = self._project_filter(project)

        # Get user messages with their session IDs
        sql = f"""
            SELECT m.session_id, m.content
            FROM messages m
            JOIN sessions s ON s.session_id = m.session_id
            WHERE m.role = 'user'
              AND m.content IS NOT NULL
              AND TRIM(m.content) != ''
              {proj_clause}
        """
        conn = self._sqlite_conn()
        try:
            messages = conn.execute(sql, proj_params).fetchall()
        finally:
            conn.close()

        # Extract concept -> sessions mapping
        concept_sessions: dict[str, set[str]] = {}
        concept_freq: dict[str, int] = {}
        for msg in messages:
            content = msg["content"] or ""
            found = set(_CONCEPT_PATTERN.findall(content.lower()))
            for concept in found:
                concept = concept.lower()
                concept_sessions.setdefault(concept, set()).add(msg["session_id"])
                concept_freq[concept] = concept_freq.get(concept, 0) + 1

        if not concept_freq:
            return 0

        # Create Concept nodes
        concept_rows = [
            {"name": name, "frequency": freq}
            for name, freq in concept_freq.items()
        ]
        cypher_concepts = """
            UNWIND $rows AS r
            MERGE (c:Concept {name: r.name})
            SET c.frequency = r.frequency
        """
        count = self._run_batched(cypher_concepts, concept_rows)

        # Link concepts to files via sessions
        proj_clause2, proj_params2 = self._project_filter(project)
        sql_files = f"""
            SELECT DISTINCT a.session_id, a.target AS path
            FROM artifacts a
            JOIN sessions s ON s.session_id = a.session_id
            WHERE a.artifact_type IN ('file_write', 'file_create')
              AND a.target NOT LIKE '%*%'
              AND a.target NOT LIKE 'tool_use:%'
              {proj_clause2}
        """
        conn = self._sqlite_conn()
        try:
            file_rows = conn.execute(sql_files, proj_params2).fetchall()
        finally:
            conn.close()

        # Build concept -> files mapping with counts
        concept_files: dict[str, dict[str, int]] = {}
        session_files: dict[str, set[str]] = {}
        for row in file_rows:
            session_files.setdefault(row["session_id"], set()).add(row["path"])

        for concept, sessions in concept_sessions.items():
            concept_files[concept] = {}
            for sid in sessions:
                for fpath in session_files.get(sid, set()):
                    concept_files[concept][fpath] = concept_files[concept].get(fpath, 0) + 1

        involves_rows = [
            {"concept": concept, "path": path, "count": cnt}
            for concept, files in concept_files.items()
            for path, cnt in files.items()
        ]
        if involves_rows:
            cypher_involves = """
                UNWIND $rows AS r
                MATCH (c:Concept {name: r.concept})
                MATCH (f:File {path: r.path})
                MERGE (c)-[i:INVOLVES]->(f)
                SET i.count = r.count
            """
            self._run_batched(cypher_involves, involves_rows)

        return count

    # ── Orchestrator ─────────────────────────────────────────────────

    def load_all(self, project: str | None = None) -> dict[str, int]:
        """Load all node and edge types. Returns counts dict."""
        self.ensure_schema()
        counts = {}
        counts["files"] = self.load_file_nodes(project)
        counts["sessions"] = self.load_session_nodes(project)
        counts["co_changes"] = self.load_co_change_edges(project)
        counts["errors"] = self.load_error_nodes(project)
        counts["tested_by"] = self.load_tested_by_edges(project)
        counts["concepts"] = self.load_concept_nodes(project)
        return counts

    def clear_graph(self) -> None:
        """Delete all nodes and edges."""
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
