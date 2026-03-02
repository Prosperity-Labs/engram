#!/usr/bin/env python3
"""Batch embed all messages in sessions.db using OpenAI text-embedding-3-small.

Contextual enrichment: prepends [Project: X | Role: Y | Tool: Z] to each message
before embedding, making vectors aware of metadata (Anthropic contextual retrieval).

Quantization: float32 → normalize → scale to [-127,127] → int8 (matches vec_messages).

Resumable: tracks progress via embed_progress table. Safe to re-run.
"""

import os
import sqlite3
import sys
import time

import numpy as np
import sqlite_vec
from openai import OpenAI

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_PATH = os.path.expanduser("~/.config/engram/sessions.db")
MODEL = "text-embedding-3-small"
DIMENSIONS = 1024
BATCH_SIZE = 100  # OpenAI supports up to 2048 inputs per call
API_KEY = os.environ.get("OPENAI_API_KEY", "")

client: OpenAI | None = None


def get_client() -> OpenAI:
    global client
    if client is None:
        client = OpenAI(api_key=API_KEY)
    return client


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    return conn


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_messages USING vec0(
            message_id INTEGER PRIMARY KEY,
            embedding int8[1024] distance_metric=cosine
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embed_progress (
            message_id INTEGER PRIMARY KEY,
            embedded_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


def get_pending_messages(conn: sqlite3.Connection) -> list[dict]:
    """Get messages that haven't been embedded yet (not in vec_messages)."""
    rows = conn.execute("""
        SELECT m.id AS message_id, m.content, m.role, m.tool_name, s.project
        FROM messages m
        LEFT JOIN sessions s ON s.session_id = m.session_id
        WHERE m.content IS NOT NULL
          AND TRIM(m.content) != ''
          AND m.id NOT IN (SELECT message_id FROM vec_messages)
        ORDER BY m.id
    """).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Contextual enrichment
# ---------------------------------------------------------------------------

def enrich_text(msg: dict) -> str:
    """Prepend contextual metadata to message content."""
    parts = []
    if msg.get("project"):
        parts.append(f"Project: {msg['project']}")
    if msg.get("role"):
        parts.append(f"Role: {msg['role']}")
    if msg.get("tool_name"):
        parts.append(f"Tool: {msg['tool_name']}")

    prefix = f"[{' | '.join(parts)}] " if parts else ""
    content = msg["content"] or ""
    # Truncate to ~8000 chars (~2000 tokens) to stay within model limits
    return (prefix + content)[:8000]


# ---------------------------------------------------------------------------
# Embedding + quantization
# ---------------------------------------------------------------------------

def embed_batch(texts: list[str]) -> np.ndarray:
    """Call OpenAI API and return int8 quantized embeddings."""
    resp = get_client().embeddings.create(
        model=MODEL,
        input=texts,
        dimensions=DIMENSIONS,
    )
    # Extract float vectors
    vecs = np.array([d.embedding for d in resp.data], dtype=np.float32)

    # Normalize
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    normalized = vecs / norms

    # Quantize to int8
    quantized = np.clip(np.rint(normalized * 127.0), -127, 127).astype(np.int8)
    return quantized


def serialize_int8(vec: np.ndarray) -> bytes:
    """Serialize an int8 vector for sqlite-vec."""
    fn = getattr(sqlite_vec, "serialize_int8", None)
    if callable(fn):
        return fn(vec)
    return bytes(memoryview(vec))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not API_KEY:
        print("ERROR: OPENAI_API_KEY not set")
        sys.exit(1)

    conn = connect()
    ensure_tables(conn)

    pending = get_pending_messages(conn)
    total = len(pending)
    if total == 0:
        existing = conn.execute("SELECT COUNT(*) FROM vec_messages").fetchone()[0]
        print(f"All messages already embedded. vec_messages count: {existing}")
        return

    print(f"Pending: {total} messages to embed")
    print(f"Model: {MODEL} (dimensions={DIMENSIONS})")
    print(f"Batch size: {BATCH_SIZE}")
    print(f"Estimated API calls: {(total + BATCH_SIZE - 1) // BATCH_SIZE}")
    print()

    embedded = 0
    errors = 0
    start_time = time.time()

    for batch_start in range(0, total, BATCH_SIZE):
        batch = pending[batch_start : batch_start + BATCH_SIZE]
        texts = [enrich_text(m) for m in batch]
        ids = [m["message_id"] for m in batch]

        try:
            vecs = embed_batch(texts)
        except Exception as e:
            errors += len(batch)
            print(f"  ERROR at batch {batch_start}: {e}")
            # On rate limit, wait and retry once
            if "rate_limit" in str(e).lower() or "429" in str(e):
                print("  Rate limited, waiting 60s...")
                time.sleep(60)
                try:
                    vecs = embed_batch(texts)
                except Exception as e2:
                    print(f"  Retry failed: {e2}")
                    continue
            else:
                continue

        # Write to vec_messages (vec0 doesn't support INSERT OR REPLACE, so delete first)
        payload = [
            (mid, serialize_int8(vecs[i]))
            for i, mid in enumerate(ids)
        ]
        try:
            for mid in ids:
                try:
                    conn.execute("DELETE FROM vec_messages WHERE message_id = ?", (mid,))
                except Exception:
                    pass
            conn.executemany(
                "INSERT INTO vec_messages(message_id, embedding) VALUES(?, vec_int8(?))",
                payload,
            )
            conn.executemany(
                "INSERT OR IGNORE INTO embed_progress(message_id) VALUES(?)",
                [(mid,) for mid in ids],
            )
            conn.commit()
            embedded += len(batch)
        except Exception as e:
            print(f"  DB ERROR at batch {batch_start}: {e}")
            conn.rollback()
            errors += len(batch)
            continue

        elapsed = time.time() - start_time
        rate = embedded / elapsed if elapsed > 0 else 0
        eta = (total - batch_start - len(batch)) / rate if rate > 0 else 0
        print(
            f"  [{embedded}/{total}] "
            f"{embedded / total * 100:.1f}% | "
            f"{rate:.0f} msgs/s | "
            f"ETA {eta:.0f}s"
        )

    elapsed = time.time() - start_time
    vec_count = conn.execute("SELECT COUNT(*) FROM vec_messages").fetchone()[0]
    conn.close()

    print(f"\nDone in {elapsed:.1f}s")
    print(f"Embedded: {embedded} | Errors: {errors}")
    print(f"vec_messages total: {vec_count}")


if __name__ == "__main__":
    main()
