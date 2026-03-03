"""Vector search helpers with graceful fallback when semantic deps are missing."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


_MODEL_REPO = "perplexity-ai/pplx-embed-context-v1-0.6b"
_EMBED_DIM = 1024
_RRF_K = 60

_TOKENIZER: Any | None = None
_ORT_SESSION: Any | None = None
_MODEL_PATH: str | None = None


def _import_sqlite_vec() -> Any | None:
    try:
        import sqlite_vec  # type: ignore
    except Exception:
        return None
    return sqlite_vec


def _import_onnxruntime() -> Any | None:
    try:
        import onnxruntime as ort  # type: ignore
    except Exception:
        return None
    return ort


def _import_numpy() -> Any | None:
    try:
        import numpy as np  # type: ignore
    except Exception:
        return None
    return np


def is_available() -> bool:
    """Return True when runtime semantic search deps are importable."""
    return _import_sqlite_vec() is not None and _import_onnxruntime() is not None


def has_embeddings(conn: Any) -> bool:
    """Return True if vec_messages table exists and has at least one row."""
    try:
        row = conn.execute("SELECT COUNT(*) FROM vec_messages").fetchone()
        return row is not None and row[0] > 0
    except Exception:
        return False


def _empty_embeddings() -> Any:
    np = _import_numpy()
    if np is None:
        return []
    return np.zeros((0, _EMBED_DIM), dtype=np.int8)


def load_model(model_name: str = "perplexity-ai/pplx-embed-context-v1-0.6b") -> tuple[Any, Any] | None:
    """Lazy-load tokenizer + ONNX session for the embed model."""
    del model_name  # fixed repo/path for now

    global _TOKENIZER, _ORT_SESSION, _MODEL_PATH
    if _TOKENIZER is not None and _ORT_SESSION is not None:
        return _TOKENIZER, _ORT_SESSION

    ort = _import_onnxruntime()
    if ort is None:
        return None

    try:
        from huggingface_hub import hf_hub_download
        from transformers import AutoTokenizer
    except Exception:
        return None

    try:
        _MODEL_PATH = hf_hub_download(repo_id=_MODEL_REPO, filename="onnx/model_quantized.onnx")
        # Download data files that the ONNX model references
        try:
            hf_hub_download(repo_id=_MODEL_REPO, filename="onnx/model_quantized.onnx_data")
        except Exception:
            pass
        _TOKENIZER = AutoTokenizer.from_pretrained(_MODEL_REPO, trust_remote_code=True)
        _ORT_SESSION = ort.InferenceSession(_MODEL_PATH, providers=["CPUExecutionProvider"])
    except Exception:
        _TOKENIZER = None
        _ORT_SESSION = None
        _MODEL_PATH = None
        return None

    return _TOKENIZER, _ORT_SESSION


def encode_int8(texts: list[str]) -> Any:
    """Encode text into int8 vectors with shape (N, 1024)."""
    np = _import_numpy()
    if np is None:
        return _empty_embeddings()

    if not texts or not is_available():
        return _empty_embeddings()

    loaded = load_model()
    if loaded is None:
        return _empty_embeddings()

    tokenizer, session = loaded

    try:
        tokenized = tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="np",
        )
    except Exception:
        return _empty_embeddings()

    try:
        input_names = {inp.name for inp in session.get_inputs()}
        ort_inputs = {
            key: val
            for key, val in tokenized.items()
            if key in input_names
        }
        if "attention_mask" in input_names and "attention_mask" not in ort_inputs:
            ort_inputs["attention_mask"] = np.ones_like(tokenized["input_ids"], dtype=np.int64)
        outputs = session.run(None, ort_inputs)
    except Exception:
        return _empty_embeddings()

    if not outputs:
        return _empty_embeddings()

    emb = outputs[0]
    if emb is None:
        return _empty_embeddings()

    emb = np.asarray(emb)
    if emb.ndim == 3:
        mask = np.asarray(tokenized.get("attention_mask"))
        if mask is None or mask.size == 0:
            pooled = emb.mean(axis=1)
        else:
            mask = mask.astype(np.float32)[..., None]
            denom = np.clip(mask.sum(axis=1), a_min=1.0, a_max=None)
            pooled = (emb * mask).sum(axis=1) / denom
    elif emb.ndim == 2:
        pooled = emb
    else:
        pooled = emb.reshape(len(texts), -1)

    if pooled.shape[1] < _EMBED_DIM:
        padded = np.zeros((pooled.shape[0], _EMBED_DIM), dtype=np.float32)
        padded[:, : pooled.shape[1]] = pooled.astype(np.float32)
        pooled = padded
    elif pooled.shape[1] > _EMBED_DIM:
        pooled = pooled[:, :_EMBED_DIM]

    pooled = pooled.astype(np.float32)
    norms = np.linalg.norm(pooled, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    normalized = pooled / norms

    quantized = np.clip(np.rint(normalized * 127.0), -127, 127).astype(np.int8)
    return quantized


def _ensure_vec_loaded(conn: Any) -> bool:
    sqlite_vec = _import_sqlite_vec()
    if sqlite_vec is None:
        return False

    try:
        conn.enable_load_extension(True)
    except Exception:
        pass

    try:
        sqlite_vec.load(conn)
    except Exception:
        # May already be loaded or unsupported by this sqlite build.
        pass

    return True


def _serialize_int8(vec: Any) -> Any:
    sqlite_vec = _import_sqlite_vec()
    if sqlite_vec is None:
        return vec

    serialize = getattr(sqlite_vec, "serialize_int8", None)
    if callable(serialize):
        return serialize(vec)

    toblob = getattr(sqlite_vec, "serialize_vector", None)
    if callable(toblob):
        return toblob(vec)

    return bytes(memoryview(vec))


def init_vec_table(conn: Any) -> None:
    """Initialize vector table if sqlite-vec is available."""
    if not _ensure_vec_loaded(conn):
        return

    try:
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_messages USING vec0(
                message_id INTEGER PRIMARY KEY,
                embedding int8[1024] distance_metric=cosine
            )
            """
        )
    except Exception:
        return


def index_message_vectors(conn: Any, messages: list[dict]) -> int:
    """Embed and index message vectors. Returns number indexed."""
    if not messages or not is_available():
        return 0

    if not _ensure_vec_loaded(conn):
        return 0

    init_vec_table(conn)

    rows: list[tuple[int, str]] = []
    for m in messages:
        message_id = m.get("message_id") or m.get("id")
        text = (m.get("content") or "").strip()
        if message_id is None or not text:
            continue
        rows.append((int(message_id), text))

    if not rows:
        return 0

    embeddings = encode_int8([text for _, text in rows])
    if getattr(embeddings, "shape", (0, 0))[0] != len(rows):
        return 0

    payload = [
        (message_id, _serialize_int8(embeddings[idx]))
        for idx, (message_id, _) in enumerate(rows)
    ]

    try:
        conn.executemany(
            "INSERT OR REPLACE INTO vec_messages(message_id, embedding) VALUES(?, vec_int8(?))",
            payload,
        )
    except Exception:
        return 0

    return len(payload)


def vector_search(conn: Any, query: str, limit: int = 20) -> list[dict]:
    """Run KNN vector search and return message_id + distance."""
    if not query.strip() or not is_available():
        return []

    if not _ensure_vec_loaded(conn):
        return []

    init_vec_table(conn)

    qvec = encode_int8([query])
    if getattr(qvec, "shape", (0, 0))[0] == 0:
        return []

    qblob = _serialize_int8(qvec[0])

    try:
        rows = conn.execute(
            """
            SELECT message_id, distance
            FROM vec_messages
            WHERE embedding MATCH vec_int8(?)
            ORDER BY distance
            LIMIT ?
            """,
            (qblob, limit),
        ).fetchall()
    except Exception:
        return []

    return [
        {"message_id": row["message_id"], "distance": row["distance"]}
        for row in rows
    ]


def _result_key(item: dict) -> Any:
    if item.get("message_id") is not None:
        return ("mid", item["message_id"])
    if item.get("id") is not None:
        return ("mid", item["id"])
    return (
        "fts",
        item.get("session_id"),
        item.get("sequence"),
        item.get("timestamp"),
        item.get("snippet"),
    )


def _fetch_messages_by_ids(conn: Any, message_ids: list[int]) -> dict[int, dict]:
    if not message_ids:
        return {}

    placeholders = ",".join("?" for _ in message_ids)
    sql = f"""
        SELECT
            m.id AS message_id,
            m.sequence,
            m.session_id,
            s.project,
            m.role,
            m.tool_name,
            m.content,
            m.timestamp
        FROM messages m
        LEFT JOIN sessions s ON s.session_id = m.session_id
        WHERE m.id IN ({placeholders})
    """

    rows = conn.execute(sql, message_ids).fetchall()
    output: dict[int, dict] = {}
    for row in rows:
        text = row["content"] or ""
        snippet = text if len(text) <= 220 else f"{text[:217]}..."
        output[row["message_id"]] = {
            "message_id": row["message_id"],
            "sequence": row["sequence"],
            "session_id": row["session_id"],
            "project": row["project"],
            "role": row["role"],
            "tool_name": row["tool_name"],
            "snippet": snippet,
            "content": row["content"],
            "timestamp": row["timestamp"],
        }
    return output


def hybrid_search(conn: Any, query: str, fts_results: list, limit: int = 20) -> list[dict]:
    """Merge FTS and vector ranking with Reciprocal Rank Fusion."""
    fts_results = fts_results or []

    vector_results = vector_search(conn, query, limit=limit * 3)
    if not fts_results and not vector_results:
        return []

    scores: dict[Any, float] = defaultdict(float)
    merged: dict[Any, dict] = {}

    for rank, item in enumerate(fts_results, start=1):
        key = _result_key(item)
        scores[key] += 1.0 / (_RRF_K + rank)
        merged[key] = dict(item)

    vector_only_ids: list[int] = []
    vector_by_key: dict[Any, dict] = {}
    for rank, item in enumerate(vector_results, start=1):
        key = _result_key(item)
        scores[key] += 1.0 / (_RRF_K + rank)
        vector_by_key[key] = item
        if key not in merged and item.get("message_id") is not None:
            vector_only_ids.append(int(item["message_id"]))

    fetched = _fetch_messages_by_ids(conn, vector_only_ids)
    for key, item in vector_by_key.items():
        if key in merged:
            merged[key]["distance"] = item.get("distance")
            continue
        message_id = item.get("message_id")
        if message_id in fetched:
            merged[key] = fetched[message_id]
            merged[key]["distance"] = item.get("distance")

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    output: list[dict] = []
    for key, score in ranked:
        row = merged.get(key)
        if not row:
            continue
        item = dict(row)
        item["rrf_score"] = score
        output.append(item)
        if len(output) >= limit:
            break

    return output
