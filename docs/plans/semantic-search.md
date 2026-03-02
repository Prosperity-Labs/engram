# Plan: Semantic Search Prototype (pplx-embed + sqlite-vec)

## Context
Engram currently uses FTS5 keyword search for session history. This works well for exact matches but misses semantically related results (e.g., searching "authentication" won't find messages about "login flow" or "OAuth tokens"). Adding vector-based semantic search using Perplexity's open-source contextual embeddings model will dramatically improve recall.

## Goal
Add vector-based semantic search using `pplx-embed-context-v1-0.6b` (MIT license, 600M params, ONNX) and `sqlite-vec` for storage. Combine with existing FTS5 keyword search via Reciprocal Rank Fusion (RRF) for hybrid search.

## Architecture

```
Query → rewrite_query() → FTS5 search (existing)
                        → vector search (new)  → RRF merge → ranked results
```

## Research Findings

### pplx-embed-context-v1-0.6b
- Perplexity's MIT-licensed contextual embedding model
- 600M params, 1024 dimensions, INT8 native output
- Based on Qwen3 decoder converted to bidirectional encoder via diffusion-based pretraining
- Contextual variant: pass chunks as grouped lists so embeddings encode session-level context
- No instruction prefix needed (unlike other embedding models)
- ONNX model available (~1.2GB, cached in ~/.cache/huggingface)
- Supports Matryoshka Representation Learning (MRL) — can truncate to 512/256 dims

### sqlite-vec
- SQLite extension for INT8 vector storage + KNN search (~300KB)
- Brute-force KNN (no ANN index), fine for <500K vectors
- Must be loaded per connection via `conn.enable_load_extension(True)`

### ONNX Inference (no PyTorch)
- `onnxruntime` (~50MB) + `transformers` (tokenizer only ~10MB)
- ~50ms per query on CPU, batch indexing ~100 msgs/sec
- Model downloaded via `hf_hub_download` to ~/.cache/huggingface

## Implementation Steps

### 1. Add optional dependencies to `pyproject.toml`
Add `[project.optional-dependencies]` section:
```toml
semantic = [
    "sqlite-vec>=0.1.1",
    "onnxruntime>=1.17.0",
    "transformers>=4.40.0",
    "numpy>=1.24.0",
]
```
Keeps base install lightweight. Users opt in with `pip install engram[semantic]`.

### 2. Create `engram/recall/vector_search.py`
New module with graceful degradation (no-ops if deps missing):

- `is_available() -> bool` — checks if sqlite-vec + onnxruntime are installed
- `load_model(model_name)` — lazy-load ONNX model + tokenizer (cached in ~/.cache/huggingface)
- `encode_int8(texts: list[str]) -> np.ndarray` — batch encode text to INT8 vectors (1024 dims)
- `init_vec_table(conn)` — create `vec_messages` virtual table if not exists
- `index_message_vectors(conn, messages)` — embed + store vectors for messages
- `vector_search(conn, query, limit) -> list[dict]` — KNN search via sqlite-vec
- `hybrid_search(conn, query, limit) -> list[dict]` — RRF combining FTS5 + vector results

Key details:
- INT8 native output (1KB per vector, not 4KB float32)
- sqlite-vec loaded per connection via `sqlite_vec.load(conn)`
- `trust_remote_code=True` required for tokenizer

### 3. Integrate into `engram/recall/session_db.py`
- In `__init__`: call `init_vec_table()` if semantic deps available
- In `index_from_session()`: after inserting messages, call `index_message_vectors()` for new messages
- Add `semantic_search(query, limit)` method that calls `hybrid_search()`

### 4. Expose via MCP server (`engram/mcp_server.py`)
- Update `engram_search()` to use hybrid search when available
- Fallback to FTS5-only when semantic deps not installed (current behavior)

### 5. Add CLI command (`engram/cli.py`)
- `engram embed` — one-time batch embedding of all existing messages
- Shows progress bar and stats (messages embedded, time taken)

### 6. Tests
- Unit tests for `vector_search.py` (mock ONNX model for CI speed)
- Integration test: index messages → hybrid search → verify ranking
- Skip tests when semantic deps not installed (`pytest.importorskip`)

## Files to Modify/Create
| File | Action | Description |
|------|--------|-------------|
| `pyproject.toml` | Modify | Add `[semantic]` optional deps |
| `engram/recall/vector_search.py` | Create | Core vector search module |
| `engram/recall/session_db.py` | Modify | Integrate vector indexing + hybrid search |
| `engram/mcp_server.py` | Modify | Use hybrid search when available |
| `engram/cli.py` | Modify | Add `engram embed` command |
| `tests/test_vector_search.py` | Create | Unit + integration tests |

## What this does NOT include
- No ANN index (sqlite-vec brute-force KNN is fine for <500K vectors)
- No GPU support (CPU-only ONNX, sufficient for query-time single embeddings)
- No model fine-tuning
- No contextual grouping yet (flat embedding, not grouped by session) — can add later

## Dependencies
| Package | Size | Purpose |
|---------|------|---------|
| sqlite-vec | ~300KB | Vector storage + KNN in SQLite |
| onnxruntime | ~50MB | ONNX model inference (no PyTorch) |
| transformers | ~10MB | Tokenizer only |
| numpy | already installed | Array ops |

## Storage Estimate
- 1KB per message (INT8 1024-dim)
- 100K messages ≈ 100MB additional DB size

## Verification
1. `pip install -e ".[semantic]"` — installs optional deps
2. `engram embed` — embeds all existing messages
3. `engram search "authentication flow"` — should find semantically related results (login, OAuth, etc.)
4. `pytest tests/test_vector_search.py` — all tests pass
5. MCP search tool returns hybrid results when semantic deps available
