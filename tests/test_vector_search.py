"""Tests for semantic vector search helpers."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from engram.recall import vector_search


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            sequence INTEGER,
            role TEXT,
            content TEXT,
            timestamp TEXT,
            tool_name TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            project TEXT
        )
        """
    )
    return conn


def test_graceful_degradation_when_deps_missing(monkeypatch):
    monkeypatch.setattr(vector_search, "_import_sqlite_vec", lambda: None)
    monkeypatch.setattr(vector_search, "_import_onnxruntime", lambda: None)

    assert vector_search.is_available() is False

    conn = _make_db()
    vector_search.init_vec_table(conn)  # no-op, should not raise

    assert vector_search.index_message_vectors(conn, [{"message_id": 1, "content": "hello"}]) == 0
    assert vector_search.vector_search(conn, "hello", limit=5) == []
    assert vector_search.hybrid_search(conn, "hello", [], limit=5) == []


@pytest.fixture
def semantic_env():
    pytest.importorskip("sqlite_vec")
    pytest.importorskip("onnxruntime")
    np = pytest.importorskip("numpy")
    return np


def test_is_available_true_when_installed(semantic_env):
    assert vector_search.is_available() is True


def test_encode_int8_shape_and_dtype(monkeypatch, semantic_env):
    np = semantic_env

    class FakeTokenizer:
        def __call__(self, texts, **kwargs):
            n = len(texts)
            return {
                "input_ids": np.ones((n, 3), dtype=np.int64),
                "attention_mask": np.ones((n, 3), dtype=np.int64),
            }

    class FakeSession:
        def get_inputs(self):
            return [SimpleNamespace(name="input_ids"), SimpleNamespace(name="attention_mask")]

        def run(self, *_args, **_kwargs):
            base = np.ones((2, 3, 1024), dtype=np.float32)
            base[1] *= 2.0
            return [base]

    monkeypatch.setattr(vector_search, "is_available", lambda: True)
    monkeypatch.setattr(vector_search, "load_model", lambda model_name="pplx-embed-context-v1-0.6b": (FakeTokenizer(), FakeSession()))

    out = vector_search.encode_int8(["one", "two"])

    assert out.shape == (2, 1024)
    assert out.dtype == np.int8


def test_init_vec_table_creates_virtual_table(semantic_env):
    conn = _make_db()
    vector_search.init_vec_table(conn)

    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='vec_messages'"
    ).fetchone()
    assert row is not None


def test_vector_search_returns_distance_sorted(monkeypatch, semantic_env):
    np = semantic_env
    conn = _make_db()
    vector_search.init_vec_table(conn)

    monkeypatch.setattr(vector_search, "encode_int8", lambda texts: np.vstack([
        np.full((1024,), 10, dtype=np.int8) if t == "alpha" else np.full((1024,), -10, dtype=np.int8)
        for t in texts
    ]))

    indexed = vector_search.index_message_vectors(
        conn,
        [
            {"message_id": 1, "content": "alpha"},
            {"message_id": 2, "content": "beta"},
        ],
    )
    assert indexed == 2

    results = vector_search.vector_search(conn, "alpha", limit=2)
    assert len(results) == 2
    assert results[0]["distance"] <= results[1]["distance"]


def test_hybrid_search_merges_via_rrf(monkeypatch, semantic_env):
    conn = _make_db()
    conn.execute("INSERT INTO sessions(session_id, project) VALUES(?, ?)", ("sess-1", "proj"))
    conn.execute(
        "INSERT INTO messages(id, session_id, sequence, role, content, timestamp, tool_name) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (2, "sess-1", 2, "assistant", "vector only message", "2026-03-01T00:00:00Z", None),
    )

    monkeypatch.setattr(
        vector_search,
        "vector_search",
        lambda _conn, _query, limit=20: [
            {"message_id": 2, "distance": 0.05},
            {"message_id": 1, "distance": 0.10},
        ],
    )

    fts_results = [
        {
            "message_id": 1,
            "session_id": "sess-1",
            "sequence": 1,
            "project": "proj",
            "role": "assistant",
            "tool_name": None,
            "snippet": "fts top",
            "content": "fts top",
            "timestamp": "2026-03-01T00:00:00Z",
        }
    ]

    merged = vector_search.hybrid_search(conn, "query", fts_results, limit=5)

    assert len(merged) == 2
    assert merged[0]["message_id"] == 1
    assert merged[1]["message_id"] == 2
    assert merged[0]["rrf_score"] >= merged[1]["rrf_score"]
