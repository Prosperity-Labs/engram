# Plan: Loopwright ↔ Paperclip Integration via Process Adapter

## Context

You use Paperclip daily for task management and agent coordination. Loopwright has self-correction (test → correct → retry) and multi-agent spawning that Paperclip lacks. Engram's proxy measures everything. The goal: wire them together so Paperclip manages tasks, Loopwright executes with self-correction, and Engram measures whether it helps.

**Key constraint**: zero Paperclip code changes. Paperclip has 649+ PRs of history — we use it as-is via its existing `process` adapter.

## Architecture

```
Paperclip (task management + UI)
  │ assigns issue to "loopwright-claude" agent
  │ triggers heartbeat → process adapter
  ▼
Loopwright paperclip-entry.ts
  │ fetches task from Paperclip API (GET /api/issues)
  │ creates git worktree for isolation
  │ runs: spawn agent → test → correct → retry (up to 3x)
  │ posts progress as issue comments back to Paperclip
  │ env: ANTHROPIC_BASE_URL=http://127.0.0.1:9080
  ▼
Claude/Codex/Cursor (spawned by Loopwright)
  │ all API calls route through Engram proxy
  ▼
Engram Proxy (:9080)
  │ logs to proxy_calls, computes session_metrics
  │ optionally injects enrichment briefs
  ▼
session_metrics: turns-to-first-edit, exploration cost, correction cycles
```

## What to Build

**Branch**: `feat/loopwright-paperclip` in the Loopwright repo

### Step 1: Loopwright Paperclip entry point (~250 lines)

**New file**: `Loopwright/src/paperclip-entry.ts`

- Reads `PAPERCLIP_API_URL`, `PAPERCLIP_AGENT_ID` from env (provided by process adapter)
- Calls Paperclip API: `GET /api/issues?assigneeAgentId={id}&status=in_progress` to get current task
- Reads issue title + description as the task prompt
- Resolves workspace from `PAPERCLIP_WORKSPACE_CWD` env or agent config cwd
- Calls existing `runLoop()` from `loop.ts` with:
  - `taskPrompt`: issue description
  - `repoPath`: workspace cwd
  - `agentType`: from `LOOPWRIGHT_AGENT_TYPE` env (default "claude")
  - `model`: from `LOOPWRIGHT_MODEL` env
  - `engramDbPath`: from `ENGRAM_DB_PATH` env
- Ensures `ANTHROPIC_BASE_URL` is set so spawned agents route through Engram proxy
- **Posts progress comments** to Paperclip issue via API after each cycle:
  - "Cycle 0: initial run complete. Running tests..."
  - "Cycle 1: 2 test failures in auth.ts. Injecting correction brief, retrying..."
  - "Result: PASSED after 2 correction cycles (3m 42s, $0.84)"
- Outputs JSON result to stdout (process adapter captures it in `resultJson`)

### Step 2: A/B enrichment experiment runner (~300 lines)

**New file**: `Loopwright/src/experiment.ts`

This is the core measurement system. Runs the SAME task twice — once enriched, once baseline — from the same git state, with a cache gap between runs.

Flow:
1. Create two git worktrees from the same HEAD
2. **Run A (enriched)**: spawn agent with `ANTHROPIC_BASE_URL` pointing to Engram proxy (enrichment ON)
3. Run tests. If passed, checkpoint the result.
4. **Wait for cache gap** (configurable, default 300s) — prevents API cache from confounding results
5. **Run B (baseline)**: spawn agent on same task, same starting commit, but with enrichment OFF (`--no-enrich` flag or separate proxy port)
6. Run tests. Checkpoint.
7. Pull metrics from Engram's `session_metrics` for both runs
8. Output comparison: turns-to-first-edit, exploration cost, total cost, correction cycles, pass/fail
9. Post comparison as Paperclip issue comment

**Key detail**: Both runs start from the same git commit. Run A can be merged, but Run B starts from the pre-merge state (its own worktree). This ensures fair comparison.

**New file**: `Loopwright/src/paperclip-experiment-entry.ts` (~120 lines)

- Fetches task from Paperclip API
- Reads `LOOPWRIGHT_CACHE_GAP_SEC=300` from env
- Delegates to `experiment.ts`
- Posts comparison table as issue comment

### Step 3: Multi-agent runner (~250 lines)

**New file**: `Loopwright/src/multi-agent.ts`

- Takes a task prompt + list of agent types (e.g., `["claude", "cursor", "codex"]`)
- Creates N parallel git worktrees from same HEAD
- Runs `runLoop()` concurrently for each agent type
- Collects per-agent results: status, cycles, duration, cost
- Returns structured comparison JSON

**New file**: `Loopwright/src/paperclip-multi-entry.ts` (~100 lines)

- Same Paperclip API integration as `paperclip-entry.ts`
- Reads `LOOPWRIGHT_AGENT_TYPES=claude,codex` from env
- Delegates to `multi-agent.ts`
- Posts comparison table as issue comment

### Step 4: Engram metrics extension (~30 lines)

**Modify**: `engram/proxy/schema.sql` + `engram/proxy/metrics.py`

- Add to `session_metrics`: `agent_type TEXT`, `correction_cycles INTEGER`, `loop_outcome TEXT`
- In `compute_metrics()`: detect Loopwright sessions by looking for multiple sequential calls with Write/Edit tools followed by test-like tool patterns
- The main tracking is already there (turns-to-first-edit, exploration cost) — just need the agent_type tag

### Step 5: Verify env passthrough

**Check**: `Loopwright/src/spawner.ts` line ~142

- Spawned agents inherit `process.env` which includes `ANTHROPIC_BASE_URL`
- Confirm this works: Loopwright sets ANTHROPIC_BASE_URL → spawns claude → claude's API calls go through Engram proxy
- No code change expected (already inherits parent env)

## Paperclip Agent Configuration (no code changes)

Create agents in Paperclip UI using `process` adapter type:

**Agent: "loopwright-claude"**
```json
{
  "command": "bun",
  "args": ["run", "/home/prosperitylabs/Desktop/development/Loopwright/src/paperclip-entry.ts"],
  "cwd": "/home/prosperitylabs/Desktop/development/engram",
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:9080",
    "LOOPWRIGHT_AGENT_TYPE": "claude",
    "ENGRAM_DB_PATH": "/home/prosperitylabs/.config/engram/sessions.db"
  },
  "timeoutSec": 1800
}
```

**Agent: "loopwright-experiment"** (A/B enrichment test)
```json
{
  "command": "bun",
  "args": ["run", "/home/prosperitylabs/Desktop/development/Loopwright/src/paperclip-experiment-entry.ts"],
  "cwd": "/home/prosperitylabs/Desktop/development/engram",
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:9080",
    "LOOPWRIGHT_AGENT_TYPE": "claude",
    "LOOPWRIGHT_CACHE_GAP_SEC": "300",
    "ENGRAM_DB_PATH": "/home/prosperitylabs/.config/engram/sessions.db"
  },
  "timeoutSec": 7200
}
```

**Agent: "loopwright-multi"** (multi-agent comparison)
```json
{
  "command": "bun",
  "args": ["run", "/home/prosperitylabs/Desktop/development/Loopwright/src/paperclip-multi-entry.ts"],
  "cwd": "/home/prosperitylabs/Desktop/development/engram",
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:9080",
    "LOOPWRIGHT_AGENT_TYPES": "claude,codex",
    "ENGRAM_DB_PATH": "/home/prosperitylabs/.config/engram/sessions.db"
  },
  "timeoutSec": 3600
}
```

## Files to Create/Modify

| File | Action | Lines |
|------|--------|-------|
| `Loopwright/src/paperclip-entry.ts` | Create | ~250 |
| `Loopwright/src/experiment.ts` | Create | ~300 |
| `Loopwright/src/paperclip-experiment-entry.ts` | Create | ~120 |
| `Loopwright/src/multi-agent.ts` | Create | ~250 |
| `Loopwright/src/paperclip-multi-entry.ts` | Create | ~100 |
| `engram/proxy/schema.sql` | Modify | +3 cols |
| `engram/proxy/metrics.py` | Modify | +30 lines |
| Paperclip | **Zero changes** | 0 |

## Implementation Order

0. Save this plan to `docs/prompts/04-loopwright-paperclip-integration.md` in the engram repo and commit
1. `paperclip-entry.ts` — get basic Loopwright-via-Paperclip working first
2. Verify proxy routing (ANTHROPIC_BASE_URL passthrough)
3. `experiment.ts` — the A/B enrichment measurement (this is the highest-value piece)
4. `multi-agent.ts` — multi-agent comparison (nice-to-have, can come later)
5. Engram metrics extension — tag sessions with agent_type and correction_cycles

## Verification

1. **Standalone test**: `PAPERCLIP_API_URL=http://localhost:3100 PAPERCLIP_AGENT_ID=test bun run src/paperclip-entry.ts` — fetches task, runs loop
2. **Proxy routing**: After a run, `engram proxy stats` shows new calls logged with the project name
3. **A/B experiment**: Run `experiment.ts` on a simple task (e.g., "add session_count() to SessionDB"). Enriched run should show fewer exploration turns than baseline. Cache gap prevents contamination.
4. **Metrics**: `engram proxy metrics --backfill` shows both runs with turns-to-first-edit comparison
5. **End-to-end via Paperclip**: Create issue, assign to loopwright-claude agent, watch progress comments appear in Paperclip UI, see results in Engram metrics
