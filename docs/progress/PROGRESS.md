# Engram Build Progress

Living document. Updated after each day's work.

---

## Day 1 — AgentAdapter + ClaudeCodeAdapter [DONE]

**Branch:** `day1/agent-adapter`
**Commits:** `2eca24e` (adapter code), `27bca0c` (tests)
**Date:** 2026-02-20

### What shipped
- `engram/adapters/base.py` — `EngramSession`, `Turn`, `ToolCall` dataclasses + `AgentAdapter` ABC
- `engram/adapters/claude_code.py` — Full JSONL parser refactored from session_db.py
- `engram/recall/session_db.py` — Added `index_from_session()` bridge; `index_session()` now uses adapter internally
- `engram/cli.py` — `cmd_install` uses `ClaudeCodeAdapter.discover_sessions()` instead of hardcoded glob
- `tests/conftest.py` — Fixtures for Claude Code (6 events) and Codex (8 events) JSONL formats
- `tests/test_base.py` — 9 tests for base data classes
- `tests/test_claude_code_adapter.py` — 12 tests for parsing, tools, tokens, project guessing, indexing, FTS

### Test results
```
21 passed in 0.12s
```

### Key decisions
- `to_message_dicts()` is the bridge from new adapter format to existing SessionDB flat schema
- Token usage includes `cache_read_input_tokens` + `cache_creation_input_tokens` (Claude Code specific)
- `EngramSession.raw_events` stores original unparsed events for future replay/audit
- Codex fixture reflects real format discovered at `~/.codex/sessions/` (not guessed)

### Recon completed (feeds Day 2 + Day 3)
- **Codex sessions:** 5 files at `~/.codex/sessions/2026/02/{02,03,17,18}/rollout-*.jsonl`
- **Codex history:** 26 entries at `~/.codex/history.jsonl` — simple `{session_id, ts, text}` format
- **Codex JSONL types:** `session_meta`, `response_item`, `event_msg`, `turn_context`
- **Codex payload types:** `message`, `function_call`, `function_call_output`, `agent_reasoning`, `token_count`
- **Cursor:** `~/.cursor/hooks.json` exists with existing hooks. `~/.cursor/sessions/` is empty (no JSONL files found)
- Cursor likely doesn't persist sessions to disk the same way — adapter will need to capture via hooks

### Backward compatibility
- `engram install` — works (discovers 233 sessions via adapter)
- `engram search` — works (FTS5 search on adapter-indexed data)
- `engram monitor` — works (snapshot reads from same SQLite)

---

## Day 2 — CursorAdapter [PENDING]

**Branch:** `day2/cursor-adapter` (not yet created)
**Goal:** Wire Cursor's `stop` hook into Engram. Cursor sessions appear in `engram inspect-list`.

---

## Day 3 — CodexAdapter [PENDING]

**Branch:** `day3/codex-adapter` (not yet created)
**Goal:** Parse `~/.codex/sessions/` JSONL files. Codex sessions appear alongside Claude Code + Cursor.
