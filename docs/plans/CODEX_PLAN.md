# Codex Task: Semantic Search for Engram

## Branch: `feat/semantic-search`

## Task
Add vector-based semantic search to engram using Perplexity's `pplx-embed-context-v1-0.6b` (MIT, ONNX) and `sqlite-vec` for storage. Combine with existing FTS5 keyword search via Reciprocal Rank Fusion (RRF).

## Full research and architecture details
Read `docs/plans/semantic-search.md` for research findings, architecture diagram, and storage estimates.

## Implementation Steps (in order)

### Step 1: Add optional dependencies to `pyproject.toml`
Add under `[project.optional-dependencies]`:
```toml
semantic = [
    "sqlite-vec>=0.1.1",
    "onnxruntime>=1.17.0",
    "transformers>=4.40.0",
    "numpy>=1.24.0",
]
```

### Step 2: Create `engram/recall/vector_search.py`
New module. Must gracefully degrade when deps are missing (return empty results, not crash).

Functions to implement:
- `is_available() -> bool` — try-import sqlite_vec + onnxruntime, return True/False
- `load_model(model_name="pplx-embed-context-v1-0.6b")` — lazy-load ONNX model via `hf_hub_download` + tokenizer via `AutoTokenizer.from_pretrained(trust_remote_code=True)`
- `encode_int8(texts: list[str]) -> np.ndarray` — tokenize, run ONNX inference, quantize to INT8, return shape (N, 1024)
- `init_vec_table(conn)` — `CREATE VIRTUAL TABLE IF NOT EXISTS vec_messages USING vec0(message_id INTEGER PRIMARY KEY, embedding int8[1024] distance_metric=cosine)`
- `index_message_vectors(conn, messages: list[dict])` — embed messages, INSERT into vec_messages
- `vector_search(conn, query: str, limit: int = 20) -> list[dict]` — encode query, KNN via `SELECT message_id, distance FROM vec_messages WHERE embedding MATCH ? ORDER BY distance LIMIT ?`
- `hybrid_search(conn, query: str, fts_results: list, limit: int = 20) -> list[dict]` — RRF merge of FTS5 + vector results: `score = 1/(k+rank_fts) + 1/(k+rank_vec)` with k=60

Important:
- sqlite-vec must be loaded per connection: `import sqlite_vec; conn.enable_load_extension(True); sqlite_vec.load(conn)`
- ONNX model path: use `huggingface_hub.hf_hub_download(repo_id="pplx/pplx-embed-context-v1-0.6b", filename="model.onnx")`
- Tokenizer: `AutoTokenizer.from_pretrained("pplx/pplx-embed-context-v1-0.6b", trust_remote_code=True)`

### Step 3: Integrate into `engram/recall/session_db.py`
- In `__init__`: after `self._migrate()`, call `vector_search.init_vec_table(self.conn)` if `vector_search.is_available()`
- In `index_from_session()`: after inserting messages into SQLite, call `vector_search.index_message_vectors(self.conn, new_messages)` if available
- Add method `semantic_search(self, query, limit=20)` that calls `vector_search.hybrid_search(self.conn, query, self.search(query, limit), limit)`

### Step 4: Expose via MCP in `engram/mcp_server.py`
- In `engram_search()`: if `vector_search.is_available()`, use `db.semantic_search(query)` instead of `db.search(query)`
- Fallback to existing FTS5 search when deps not installed

### Step 5: Add CLI command in `engram/cli.py`
- Add `engram embed` subcommand that batch-embeds all existing messages
- Query all messages from DB, batch encode (batch_size=64), insert vectors
- Print progress: "Embedding messages... X/Y" and final stats

### Step 6: Tests in `tests/test_vector_search.py`
- Use `pytest.importorskip("sqlite_vec")` to skip when deps missing
- Test `is_available()` returns True when deps installed
- Test `encode_int8()` returns correct shape (N, 1024) and dtype int8
- Test `init_vec_table()` creates the virtual table
- Test `vector_search()` returns results sorted by distance
- Test `hybrid_search()` merges FTS5 + vector results via RRF
- Test graceful degradation: when deps missing, functions return empty/no-op

## Key Files
| File | Action |
|------|--------|
| `pyproject.toml` | Modify — add optional deps |
| `engram/recall/vector_search.py` | Create — core vector module |
| `engram/recall/session_db.py` | Modify — integrate vector indexing + search |
| `engram/mcp_server.py` | Modify — use hybrid search when available |
| `engram/cli.py` | Modify — add `engram embed` command |
| `tests/test_vector_search.py` | Create — tests |

## Verification
```bash
pip install -e ".[semantic]"
engram embed
engram search "authentication flow"
pytest tests/test_vector_search.py -v
pytest tests/ -v  # ensure existing tests still pass
```

## Constraints
- Never crash when semantic deps are missing — always graceful degradation
- No PyTorch dependency (ONNX only)
- INT8 vectors (1KB each), not float32
- Do not modify existing FTS5 search behavior — hybrid search is additive
- Existing tests must continue to pass
