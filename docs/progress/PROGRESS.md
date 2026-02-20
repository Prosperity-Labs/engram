# Engram Build Progress

Living document. Updated after each day's work.

---

## Day 1 — AgentAdapter + ClaudeCodeAdapter [DONE]

**Branch:** `day1/agent-adapter`
**Commits:** `2eca24e`, `27bca0c`, `480bb1f`, `ce467eb`

### What shipped
- `engram/adapters/base.py` — EngramSession, Turn, ToolCall dataclasses + AgentAdapter ABC
- `engram/adapters/claude_code.py` — Full JSONL parser refactored from session_db.py
- `engram/recall/session_db.py` — index_from_session() bridge; index_session() uses adapter
- `engram/cli.py` — cmd_install uses ClaudeCodeAdapter.discover_sessions()
- `tests/` — conftest.py fixtures, test_base.py (9), test_claude_code_adapter.py (12) = 21 tests

### Recon for Day 2/3
- Codex: 5 sessions at `~/.codex/sessions/`, history at `~/.codex/history.jsonl`
- Cursor: `~/.cursor/hooks.json` has hooks, no disk sessions
- Delegation plans written: day2-cursor-adapter.md, day3-codex-adapter.md

---

## Day 1.5 — Public API + Granular Token Costs [DONE]

**Branch:** `fix/public-api-and-costs`
**Commit:** `5b09611`

### What shipped
- `engram/__init__.py` — Public API: `from engram import SessionIndexer, search`
- Granular token schema: `cache_read_tokens`, `cache_create_tokens` columns (auto-migrates)
- `session_costs()` method with Opus pricing model
- CLI: `engram costs` — per-session cost breakdown
- CLI: `engram reindex` — backfills granular token data from raw JSONL
- `SessionDB.install()` convenience method

### Key finding
Cost estimates were 6-15x overstated when cache_read tokens ($1.50/M) were lumped with input ($15/M).
- This session: $60.56 actual vs $839 original estimate
- Biggest session: ~$300 actual vs ~$2,200 original estimate

### Verification results

| Test | Status |
|---|---|
| `from engram import SessionIndexer` | PASS |
| `search('webhook')` | PASS — returns highlighted FTS results |
| `engram costs` | PASS — shows per-session breakdown with * for needs-re-index |
| `pip install -e .` in clean venv | PASS — all imports resolve |
| 21 pytest tests | PASS in 0.07s |

---

## Day 2 — CursorAdapter [PENDING]

**Branch:** `day2/cursor-adapter` (not yet created)
**Spec:** `docs/plans/day2-cursor-adapter.md`

---

## Day 3 — CodexAdapter [PENDING]

**Branch:** `day3/codex-adapter` (not yet created)
**Spec:** `docs/plans/day3-codex-adapter.md`
