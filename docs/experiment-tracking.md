# Experiment Tracking — Context System Comparison

> Tracking 4 systems: Engram, Claude-mem, Noodlbox, tiiny.site approach
> Baseline: 2026-02-23 | Last check: 2026-02-23 (same day — no delta yet)

## Systems Under Observation

| System | What it does | How it works | Status |
|--------|-------------|--------------|--------|
| **Engram** | Session history → CLAUDE.md + file context | PreToolUse hook injects file history, SessionStart hook generates brief | Active on monra.app |
| **Claude-mem** | AI-curated observations + vector search | PostToolUse hook captures observations, MCP tools for retrieval | Active (systemd, port 37777) |
| **Noodlbox** | Code knowledge graph via MCP | Agent calls on-demand for semantic search, symbol context, impact analysis | Active (4 repos indexed) |
| **tiiny.site approach** | FTS5 search API + UserPromptSubmit hook | Agent actively curls localhost for context (not installed — reference only) | Not installed |

## Current Readings (2026-02-23)

### Engram
```
Sessions:        290 (no change from baseline)
Messages:        52,284
Artifacts:       16,303
Cache efficiency: 85%

monra-app (28 sessions):
  Exploration: 29%    (baseline: 29% — no change yet)
  Mutation:    12%
  Execution:   42%
```

### Claude-mem
```
Worker:       v9.0.5, uptime 13.4 hours, port 37777
Observations: 585    (baseline: 585 — no new observations)
Sessions:     52
Summaries:    0
DB size:      2.8 MB
Last obs:     2026-02-19 (4 days ago)
```
**Note:** No new observations since baseline. Worker is running but no monra.app
sessions have happened since we set it up. Need to do real work in monra.app
and check if PostToolUse hooks are firing.

### Noodlbox
```
Tool calls:   103 total (baseline: 103 — no change)
  query_with_context: 58
  raw_cypher_query:   22
  symbol_context:     20
  analyze:            3

Repos: 4 indexed (788 MB for monra.app alone)
```
**Note:** Noodlbox calls only happen when agents actively query it.
This session used it heavily (competitive analysis), but those calls
were in engram/openclaw projects, not monra-app.

### tiiny.site approach
```
Status: NOT INSTALLED
```
The tiiny.site approach (FastAPI + FTS5 + UserPromptSubmit hook injecting
search reminders) is a reference architecture only. We decided not to build
an MCP server — claude-mem already fills that role.

The key insight from tiiny.site: 80% token savings on search comes from
SQLite FTS5 `snippet()` returning ~32 words vs full messages. Engram already
has FTS5 but doesn't expose it via MCP.

## Tracking Table

| Metric | Baseline (Feb 23) | Current (Feb 23) | Delta | Target |
|--------|-------------------|-------------------|-------|--------|
| Exploration % (monra-app) | 29% | 29% | — | <20% |
| Cache efficiency | 85% | 85% | — | >90% |
| Claude-mem observations | 585 | 585 | +0 | growing |
| Noodlbox tool calls | 103 | 103 | +0 | growing |
| Messages to first Edit | ~54 (median) | not measured | — | <30 |
| Engram sessions | 290 | 290 | +0 | growing |
| Engram artifacts | 16,303 | 16,303 | +0 | growing |

**Verdict: No delta yet.** The baseline was captured hours ago. Real measurement
starts after 5-10 monra-app work sessions. Re-check in ~1 week.

## How to Re-check

```bash
# Run from engram directory with venv active
cd ~/Desktop/development/engram

# 1. Engram exploration ratio
.venv/bin/engram stats --project monra-app

# 2. Engram cache efficiency
.venv/bin/engram insights

# 3. Claude-mem observations
curl -s http://127.0.0.1:37777/api/stats | python3 -m json.tool

# 4. Noodlbox usage
.venv/bin/engram artifacts --type api_call --project monra-app --limit 50

# 5. Quick summary
echo "=== Quick Check ===" && \
.venv/bin/python3 -c "
import sqlite3, json
db = sqlite3.connect('/home/prosperitylabs/.config/engram/sessions.db')
sess = db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
arts = db.execute('SELECT COUNT(*) FROM artifacts').fetchone()[0]
noodl = db.execute(\"SELECT COUNT(*) FROM artifacts WHERE target LIKE '%noodlbox%'\").fetchone()[0]
print(f'Sessions: {sess}, Artifacts: {arts}, Noodlbox calls: {noodl}')
" && \
curl -s http://127.0.0.1:37777/api/stats 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f\"Claude-mem: {d['database']['observations']} observations, {d['database']['sessions']} sessions\")
" 2>/dev/null || echo "Claude-mem worker not responding"
```

## What We Decided (from DIRECTION.md)

- **Stop building features.** Three systems are live. Measure, don't build.
- **No MCP server for Engram** (claude-mem already has one)
- **No vector search** (claude-mem already has ChromaDB)
- **No web UI** (claude-mem already has one)

## New Direction: Observability Product (from this session)

While tracking context system usefulness, we discovered a more valuable angle:

**Engram as AI Agent Observability** — not "make agents faster" but "make agents auditable."

Key findings from analyzing our own 16,303 artifacts:
- 110 sensitive file accesses (.env, tokens, Dockerfiles) — zero alerts
- 10 burn sessions (high cost, zero output) — zero notifications
- 8 hotspot files being constantly rewritten — zero human review
- 1 session (Dec 24) burned 426 messages on a webhook failure — zero escalation

**Enterprise value tiers** (highest to lowest):
1. Security: sensitive file access detection ($50-200K/yr)
2. Accountability: session-to-commit forensic linking ($30-100K/yr)
3. Compliance: SOC2/EU AI Act audit trail ($50-150K/yr)
4. Risk: pre-merge blast radius assessment ($20-50K/yr)
5. Cost: token waste detection ($5-10K/yr)

**Next step:** LinkedIn validation posts (see `docs/linkedin-validation.md`)

## Files Related to This Experiment

- `docs/DIRECTION.md` — High-level decision document
- `docs/baseline-2026-02-23.md` — Full baseline metrics
- `docs/experiment-tracking.md` — This file (re-check tracker)
- `docs/linkedin-validation.md` — LinkedIn posts for demand validation
- `engram/brief.py` — Brief fixes (uncommitted)
- `engram/hooks/__init__.py` — Hook improvements (uncommitted)
- `engram/hooks/session-start.sh` — SessionStart hook (uncommitted)
