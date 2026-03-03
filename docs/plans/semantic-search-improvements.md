# Semantic Search Improvements

Tracked improvements for `feat/semantic-search` branch.

## Critical — Fix before merge

1. **Guard hybrid search when no embeddings exist** — `is_available()` returns `True` if ONNX deps are installed, even with zero embeddings in the DB. First MCP search triggers a multi-GB model download that freezes the server. Fix: check `vec_messages` count before routing to `semantic_search()`.

2. **Add `huggingface-hub` to `[semantic]` dependencies** — `vector_search.py` imports `hf_hub_download` but the package isn't in `pyproject.toml`. Works today only because `transformers` pulls it transitively.

3. **Silent result drops in hybrid search** — Vector-only matches whose `message_id` isn't found in `messages` table are silently dropped. Should log a warning.

## High — Should do on this branch

4. **`engram embed` has no resume/progress tracking** — If interrupted, restarts from scratch. The OpenAI batch script has `embed_progress` but the CLI command doesn't use it.

5. **Add `engram embed --status`** — No way to check how many messages are embedded vs total. Users need visibility.

6. **Remove unused `model_name` parameter** from `load_model()` — it's immediately `del`'d.

7. **Extract shared `quantize_to_int8()` function** — Same normalization + quantization logic exists in both `vector_search.encode_int8()` and `batch_embed_openai.py`.

## Medium — Quality improvements

8. **Query rewriter stopwords too aggressive** — "test", "fix", "find" are stopworded but are common meaningful search terms.

9. **Add E2E test** — No test covers the full install → embed → search workflow, or the MCP `engram_search` tool with hybrid search.

10. **Make RRF `k=60` tunable** — Hardcoded constant controls FTS vs vector weight balance. Should be configurable.

11. **Support OpenAI for query-time encoding** — Currently queries are encoded with local ONNX only. If ONNX isn't installed but `OPENAI_API_KEY` is set and embeddings exist, could use OpenAI for the single query vector.

## Nice to have

12. **Embedding metadata** — `vec_messages` stores only `(message_id, embedding)`. Adding `model`, `embedded_at` would help track staleness.

13. **`engram embed --clear`** — Wipe `vec_messages` to start fresh with a different model.

14. **Semantic filtering by project/session** — Vector search returns results from all projects. Could add metadata-aware filtering.

15. **Brief/hooks integration** — `brief.py` and artifact extraction don't leverage semantic search yet.

---

## Roadmap — Live/Streaming Indexing

### Problem

Engram currently requires manual `engram install` or `engram monitor` to index sessions. The active session is never searchable until after it's closed and re-indexed. This means:
- `engram_recall` can't find work done in the current session or recent sessions
- Users must remember to run `engram install` after sessions end
- There's a blind spot between "last index" and "now" that grows over time

### Proposed Solution: Streaming Indexer

A filesystem watcher that indexes JSONL lines as they're appended to session files.

**Architecture:**
1. **`inotify`/`watchdog` watcher** on `~/.claude/projects/*/` — detects JSONL file modifications
2. **Incremental parser** — reads only new lines appended since last read (track file offset per session)
3. **Live `index_session()` calls** — insert new messages into SQLite as they arrive
4. **Debounce** — batch appends over a short window (1-2s) to avoid excessive DB writes
5. **Embedding queue** — optionally queue new messages for async embedding (if OpenAI key is set)

**Key Design Decisions:**
- Parse from raw JSONL (same as artifact trail), not wait for session close
- Use `watchdog` library (cross-platform) or `inotify` (Linux-only, lower overhead)
- Handle the active session's JSONL being written to concurrently — need file locking or append-only reads
- Skip `summary` and `progress` types during live indexing (same as current batch indexing)

**CLI:**
```bash
engram monitor --watch          # Already exists, runs continuous polling
engram monitor --live           # New: streaming mode with filesystem watcher
engram monitor --live --embed   # Live index + queue embeddings
```

**Integration points:**
- `session_db.py` — add `index_message()` for single-message inserts (vs batch `index_session()`)
- `mcp_server.py` — no changes needed (already queries SQLite)
- `cli.py` — extend `monitor` command with `--live` flag

**Complexity estimate:** Medium — the core logic is straightforward (watch + parse + insert), but handling concurrent file writes, crash recovery (offset tracking), and embedding queue adds complexity.

**Dependencies:** `watchdog` (new optional dep in `[live]` extra)
