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

### Full re-index results (243 sessions)
- Total cost: $3,151 across 243 sessions (avg $15.15/session)
- Cache efficiency: 91.9% of input tokens are cache reads
- Without caching: $17,947 — 81% saved by prompt caching
- Most expensive session: $299 (planning session, high output tokens)
- Most expensive per-message: $0.34/msg (a planning-heavy session)
- Tool breakdown: Bash 2x most used, then Read, Edit, Write, Grep, Glob

### Verification results

| Test | Status |
|---|---|
| `from engram import SessionIndexer` | PASS |
| `search('webhook')` | PASS — returns highlighted FTS results |
| `engram costs` | PASS — shows per-session breakdown with * for needs-re-index |
| `pip install -e .` in clean venv | PASS — all imports resolve |
| 21 pytest tests | PASS in 0.07s |

---

## Day 1.75 — Insights Command [DONE]

**Branch:** `feat/insights-command`
**Commit:** `7f4fbf5`

### What shipped
- `engram/recall/session_db.py` — `insights()` method (161 lines, 8 SQL analytics queries)
- `engram/cli.py` — `cmd_insights` with formatted dashboard + `--json` flag
- `_short_project()` helper strips Claude Code path-encoded project names to readable form
- 21 tests pass, no regressions

### Analytics available via `engram insights`
- Cache efficiency: hit rates, actual cost vs without-cache, savings %
- Top tools: ranked by usage count with bar chart
- Projects: sessions and messages per project (readable names)
- Messages by role: user/assistant/summary counts
- Coding hours: session start times as histogram
- Most expensive per-message: cost outlier sessions
- Error-heavy sessions: ranked by error rate
- Topics: keyword frequency across sessions

### Key findings from first run (243 sessions)
- $3,568 total spend, $14,533 saved by caching (80%)
- Bash 2.3x more used than Read — suggests "try it" over "read first" pattern
- webhook, deposit, withdraw topics span 90-123 sessions each — recurring issues not solved durably
- One session hit 24% error rate (agent spinning on AWS ResourceNotFoundException)
- openclaw session: $0.43/msg, 2x more expensive than next highest

---

## Day 2 — CursorAdapter [PENDING]

**Branch:** `day2/cursor-adapter` (not yet created)
**Spec:** `docs/plans/day2-cursor-adapter.md`

---

## Day 3 — CodexAdapter [PENDING]

**Branch:** `day3/codex-adapter` (not yet created)
**Spec:** `docs/plans/day3-codex-adapter.md`
