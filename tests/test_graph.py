"""Tests for the Engram knowledge graph module.

Auto-skips if Memgraph is not running or neo4j is not installed.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

neo4j = pytest.importorskip("neo4j")


def _memgraph_available() -> bool:
    """Check if Memgraph is reachable on localhost:7687."""
    try:
        driver = neo4j.GraphDatabase.driver("bolt://localhost:7687")
        driver.verify_connectivity()
        driver.close()
        return True
    except Exception:
        return False


requires_memgraph = pytest.mark.skipif(
    not _memgraph_available(),
    reason="Memgraph not running on bolt://localhost:7687",
)


def _create_seed_db(db_path: str) -> None:
    """Create a minimal SQLite DB matching Engram's schema with test data."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            filepath TEXT NOT NULL,
            project TEXT,
            message_count INTEGER DEFAULT 0,
            file_size_bytes INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        );

        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL REFERENCES sessions(session_id),
            sequence INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            timestamp TEXT,
            tool_name TEXT,
            token_usage_in INTEGER DEFAULT 0,
            token_usage_out INTEGER DEFAULT 0,
            cache_read_tokens INTEGER DEFAULT 0,
            cache_create_tokens INTEGER DEFAULT 0,
            agent_id TEXT,
            UNIQUE(session_id, sequence)
        );

        CREATE TABLE artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            target TEXT NOT NULL,
            tool_name TEXT,
            sequence INTEGER,
            context TEXT,
            UNIQUE(session_id, artifact_type, target, sequence)
        );

        -- Session 1: working on auth
        INSERT INTO sessions VALUES ('sess-001', '/tmp/s1.jsonl', 'test-project', 5, 1024, '2026-01-01T10:00:00', '2026-01-01T11:00:00');
        -- Session 2: working on auth + database
        INSERT INTO sessions VALUES ('sess-002', '/tmp/s2.jsonl', 'test-project', 3, 512, '2026-01-02T10:00:00', '2026-01-02T10:30:00');

        -- Messages for session 1
        INSERT INTO messages (session_id, sequence, role, content, token_usage_in, token_usage_out, cache_read_tokens, cache_create_tokens)
        VALUES
            ('sess-001', 1, 'user', 'Fix the authentication bug in the login handler', 100, 0, 50, 10),
            ('sess-001', 2, 'assistant', 'I will read the auth module.', 0, 200, 0, 0),
            ('sess-001', 3, 'assistant', 'Editing the file now.', 0, 150, 0, 0),
            ('sess-001', 4, 'assistant', 'Error: ModuleNotFoundError: No module named flask', 0, 50, 0, 0),
            ('sess-001', 5, 'user', 'We need to fix the database connection too', 120, 0, 60, 15);

        -- Messages for session 2
        INSERT INTO messages (session_id, sequence, role, content, token_usage_in, token_usage_out, cache_read_tokens, cache_create_tokens)
        VALUES
            ('sess-002', 1, 'user', 'Add deployment configuration for docker', 80, 0, 40, 8),
            ('sess-002', 2, 'assistant', 'Setting up docker config.', 0, 180, 0, 0),
            ('sess-002', 3, 'assistant', 'Done with the testing setup.', 0, 100, 0, 0);

        -- Artifacts for session 1
        INSERT INTO artifacts (session_id, artifact_type, target, tool_name, sequence) VALUES
            ('sess-001', 'file_read', 'src/auth/login.py', 'Read', 2),
            ('sess-001', 'file_write', 'src/auth/login.py', 'Edit', 3),
            ('sess-001', 'file_write', 'src/auth/utils.py', 'Edit', 3),
            ('sess-001', 'file_create', 'tests/test_auth.py', 'Write', 4),
            ('sess-001', 'error', 'ModuleNotFoundError: No module named flask', NULL, 4),
            ('sess-001', 'command', 'pip install flask', 'Bash', 5);

        -- Artifacts for session 2
        INSERT INTO artifacts (session_id, artifact_type, target, tool_name, sequence) VALUES
            ('sess-002', 'file_write', 'src/auth/login.py', 'Edit', 2),
            ('sess-002', 'file_write', 'src/auth/utils.py', 'Edit', 2),
            ('sess-002', 'file_create', 'docker/Dockerfile', 'Write', 3),
            ('sess-002', 'file_write', 'tests/test_auth.py', 'Edit', 3),
            ('sess-002', 'error', 'ModuleNotFoundError: No module named flask', NULL, 3);
    """)
    conn.close()


@pytest.fixture
def seed_db(tmp_path):
    """Create a temporary SQLite DB with test data."""
    db_path = tmp_path / "test_sessions.db"
    _create_seed_db(str(db_path))
    return str(db_path)


@pytest.fixture
def graph_driver():
    """Create a Memgraph driver."""
    driver = neo4j.GraphDatabase.driver("bolt://localhost:7687")
    yield driver
    driver.close()


@pytest.fixture
def graph_loader(seed_db, graph_driver):
    """Create a GraphLoader wired to the seed DB, clearing graph before/after."""
    from engram.graph.loader import GraphLoader

    loader = GraphLoader(graph_driver, db_path=seed_db)
    loader.clear_graph()
    yield loader
    loader.clear_graph()


@requires_memgraph
class TestLoadFileNodes:
    def test_creates_file_nodes(self, graph_loader, graph_driver):
        count = graph_loader.load_file_nodes()
        assert count > 0

        with graph_driver.session() as s:
            files = [r["path"] for r in s.run("MATCH (f:File) RETURN f.path AS path")]
        assert "src/auth/login.py" in files
        assert "src/auth/utils.py" in files

    def test_sets_properties(self, graph_loader, graph_driver):
        graph_loader.load_file_nodes()

        with graph_driver.session() as s:
            login = s.run(
                "MATCH (f:File {path: 'src/auth/login.py'}) RETURN f.read_count AS rc, f.write_count AS wc, f.name AS name"
            ).single()
        assert login["rc"] == 1  # read once in sess-001
        assert login["wc"] == 2  # written in both sessions
        assert login["name"] == "login.py"

    def test_idempotent(self, graph_loader, graph_driver):
        count1 = graph_loader.load_file_nodes()
        count2 = graph_loader.load_file_nodes()
        assert count1 == count2

        with graph_driver.session() as s:
            total = s.run("MATCH (f:File) RETURN count(f) AS c").single()["c"]
        # Should not duplicate nodes
        assert total == count1

    def test_project_filter(self, graph_loader, graph_driver):
        count = graph_loader.load_file_nodes(project="nonexistent")
        assert count == 0


@requires_memgraph
class TestLoadSessionNodes:
    def test_creates_session_nodes(self, graph_loader, graph_driver):
        graph_loader.load_file_nodes()  # need files first for TOUCHED edges
        count = graph_loader.load_session_nodes()
        assert count == 2

        with graph_driver.session() as s:
            sessions = [r["id"] for r in s.run("MATCH (s:Session) RETURN s.id AS id")]
        assert "sess-001" in sessions
        assert "sess-002" in sessions

    def test_cost_computed(self, graph_loader, graph_driver):
        graph_loader.load_file_nodes()
        graph_loader.load_session_nodes()

        with graph_driver.session() as s:
            sess = s.run("MATCH (s:Session {id: 'sess-001'}) RETURN s.cost AS cost").single()
        assert sess["cost"] > 0

    def test_touched_edges(self, graph_loader, graph_driver):
        graph_loader.load_file_nodes()
        graph_loader.load_session_nodes()

        with graph_driver.session() as s:
            edges = s.run(
                "MATCH (s:Session {id: 'sess-001'})-[t:TOUCHED]->(f:File) RETURN f.path AS path, t.write_count AS wc"
            )
            touched = {r["path"]: r["wc"] for r in edges}
        assert "src/auth/login.py" in touched
        assert touched["src/auth/login.py"] == 1  # one write in sess-001


@requires_memgraph
class TestLoadCoChangeEdges:
    def test_creates_co_change_edges(self, graph_loader, graph_driver):
        graph_loader.load_file_nodes()
        count = graph_loader.load_co_change_edges()
        assert count > 0

        with graph_driver.session() as s:
            edges = [
                (r["a"], r["b"])
                for r in s.run(
                    "MATCH (f1:File)-[:CO_CHANGES_WITH]->(f2:File) RETURN f1.path AS a, f2.path AS b"
                )
            ]
        # login.py and utils.py are modified together in both sessions
        assert any(
            ("src/auth/login.py" in (a, b) and "src/auth/utils.py" in (a, b))
            for a, b in edges
        )


@requires_memgraph
class TestLoadErrorNodes:
    def test_creates_error_nodes(self, graph_loader, graph_driver):
        graph_loader.load_file_nodes()
        count = graph_loader.load_error_nodes()
        assert count > 0

        with graph_driver.session() as s:
            errors = [r["p"] for r in s.run("MATCH (e:Error) RETURN e.pattern AS p")]
        assert any("ModuleNotFoundError" in p for p in errors)

    def test_causes_error_edges(self, graph_loader, graph_driver):
        graph_loader.load_file_nodes()
        graph_loader.load_error_nodes()

        with graph_driver.session() as s:
            edges = s.run(
                "MATCH (f:File)-[:CAUSES_ERROR]->(e:Error) RETURN f.path AS path, e.pattern AS pattern"
            )
            causes = [(r["path"], r["pattern"]) for r in edges]
        # Files written near errors should have CAUSES_ERROR edges
        assert len(causes) > 0


@requires_memgraph
class TestLoadTestedByEdges:
    def test_infers_tested_by(self, graph_loader, graph_driver):
        graph_loader.load_file_nodes()
        graph_loader.load_co_change_edges()
        count = graph_loader.load_tested_by_edges()

        # tests/test_auth.py co-changes with src/auth/login.py and utils.py
        with graph_driver.session() as s:
            edges = [
                (r["src"], r["test"])
                for r in s.run(
                    "MATCH (f:File)-[:TESTED_BY]->(t:File) RETURN f.path AS src, t.path AS test"
                )
            ]
        if count > 0:
            assert any("test_auth" in test for _, test in edges)


@requires_memgraph
class TestLoadConceptNodes:
    def test_creates_concept_nodes(self, graph_loader, graph_driver):
        graph_loader.load_file_nodes()
        count = graph_loader.load_concept_nodes()
        assert count > 0

        with graph_driver.session() as s:
            concepts = [r["name"] for r in s.run("MATCH (c:Concept) RETURN c.name AS name")]
        assert "authentication" in concepts  # from "authentication bug" in user message

    def test_involves_edges(self, graph_loader, graph_driver):
        graph_loader.load_file_nodes()
        graph_loader.load_concept_nodes()

        with graph_driver.session() as s:
            edges = s.run(
                "MATCH (c:Concept)-[:INVOLVES]->(f:File) RETURN c.name AS concept, f.path AS path"
            )
            involves = [(r["concept"], r["path"]) for r in edges]
        # auth concept should involve files from session 1
        assert len(involves) > 0


@requires_memgraph
class TestLoadAll:
    def test_returns_all_counts(self, graph_loader):
        counts = graph_loader.load_all()
        assert "files" in counts
        assert "sessions" in counts
        assert "co_changes" in counts
        assert "errors" in counts
        assert "tested_by" in counts
        assert "concepts" in counts
        assert counts["files"] > 0
        assert counts["sessions"] > 0

    def test_idempotent(self, graph_loader):
        counts1 = graph_loader.load_all()
        counts2 = graph_loader.load_all()
        assert counts1["files"] == counts2["files"]
        assert counts1["sessions"] == counts2["sessions"]


@requires_memgraph
class TestClearGraph:
    def test_clears_all(self, graph_loader, graph_driver):
        graph_loader.load_all()

        with graph_driver.session() as s:
            before = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        assert before > 0

        graph_loader.clear_graph()

        with graph_driver.session() as s:
            after = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
        assert after == 0


@requires_memgraph
class TestAlgorithms:
    def test_pagerank(self, graph_loader, graph_driver):
        graph_loader.load_all()

        from engram.graph.algorithms import run_pagerank
        results = run_pagerank(graph_driver)
        assert isinstance(results, list)
        if results:
            assert "path" in results[0]
            assert "rank" in results[0]

    def test_community_detection(self, graph_loader, graph_driver):
        graph_loader.load_all()

        from engram.graph.algorithms import run_community_detection
        results = run_community_detection(graph_driver)
        assert isinstance(results, list)
        if results:
            assert "community_id" in results[0]
            assert "files" in results[0]

    def test_shortest_path(self, graph_loader, graph_driver):
        graph_loader.load_all()

        from engram.graph.algorithms import run_shortest_path
        results = run_shortest_path(graph_driver)
        assert isinstance(results, list)

    def test_run_algorithms_all(self, graph_loader, graph_driver):
        graph_loader.load_all()

        from engram.graph.algorithms import run_algorithms
        results = run_algorithms(graph_driver, algorithm="all")
        assert isinstance(results, dict)
        # Should have attempted all three
        total_keys = set(results.keys()) - {"errors"}
        assert len(total_keys) > 0
