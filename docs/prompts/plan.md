# Engram Enrichment Plan — Multi-Session Execution

## What We're Building

Context engineering for AI agents, proven by measurement.

Not just "inject memory" — prove which memory helps, then inject the
best context automatically. The proxy sees every API call at the wire
level. That's the surface where we test, measure, and optimize.

## Why This Matters (Differentiation)

Claude-mem has structured observations, typed memories, progressive
disclosure — polished memory storage. But they don't measure whether
their context actually helps. They inject and hope.

Engram's edge:
- **Proxy interception** — sees every call, any agent, no hooks needed
- **Knowledge graph** — Memgraph with co-change/error/community data
- **Measurement** — session_metrics, A/B, turns-to-first-edit
- **Session replay** — can reproduce starting context and test variants

The plan: fix the enrichment quality, connect the graph, measure
everything, then prove the value with automated experiments.

---

## Session 1: Fix Enrichment Quality + Connect Memgraph

### Agent Instructions

```
Read these files first:
- docs/prompts/01-improve-enrichment-brief.md (requirements)
- engram/proxy/enrichment.py (project resolution bug)
- engram/brief.py (brief generation)
- engram/graph/algorithms.py (PageRank, community detection)
- engram/graph/loader.py (graph schema context)

Do these things in order:

1. FIX _resolve_project() in enrichment.py
   - Don't pick exact match first. Query ALL project variants
     that match (exact, suffix, contains) and AGGREGATE them.
   - Return the variant with the most sessions, OR combine data
     from all variants into a single brief.
   - Test: "engram" should resolve to the full path with 25 sessions,
     not the short name with 5.

2. FIX Key Decisions truncation in brief.py
   - Line 472: snippet[:120] cuts mid-sentence.
   - Use sentence boundary detection: find last '. ' before 200 chars.
   - If no period found, cut at last space before 200 chars + '...'

3. ADD optional Memgraph enrichment to brief.py
   - Create _graph_enrichment(project) that:
     a) Tries to connect to Memgraph (bolt://localhost:7687)
     b) If available, queries:
        - PageRank top 5 files for this project (most central)
        - Community detection clusters (functional modules)
        - Error propagation chains (File → CAUSES_ERROR → Error)
     c) Returns structured data or empty dict if unavailable
   - Integrate into generate_slim_brief():
     - Add "## Central Files (graph)" section if PageRank data exists
     - Add "## Functional Modules" section if communities exist
     - Keep it optional — SQLite sections always work, graph sections
       are bonus when Memgraph is running

4. TEST by running before/after comparison:
   python -c "
   from engram.recall.session_db import SessionDB
   from engram.brief import generate_slim_brief
   db = SessionDB()
   for proj in ['engram', 'monra-core', 'openclaw', 'Loopwright']:
       print(f'=== {proj} ===')
       print(generate_slim_brief(db, proj))
       print()
   "

5. Show me the before and after output for each project.

Context: The proxy currently injects these briefs into Anthropic API
system prompts. Better briefs = agents that explore less and edit
sooner. We're measuring this in the next prompt.
```

### Acceptance Criteria
- `_resolve_project("engram")` finds the variant with most sessions
- No brief is a one-liner "explored codebase. N messages"
- Key Decisions don't cut mid-sentence
- If Memgraph is running: PageRank and community data appear in brief
- If Memgraph is NOT running: brief still works, just without graph sections

---

## Session 2: Automated Session Metrics

### Agent Instructions

```
Read these files first:
- docs/prompts/02-automated-session-metrics.md (requirements)
- docs/prompts/plan.md (this file — strategic context)
- engram/proxy/enrichment.py (to understand enrichment_variant)
- engram/proxy/bun/proxy.ts (to understand proxy_calls table)

Do these things:

1. CREATE engram/proxy/metrics.py
   - Add session_metrics table to sessions.db:
     CREATE TABLE IF NOT EXISTS session_metrics (
         session_id TEXT PRIMARY KEY,
         project TEXT,
         enrichment_variant TEXT,
         turns_to_first_edit INTEGER,
         exploration_turns INTEGER,
         exploration_cost_usd REAL,
         total_turns INTEGER,
         total_cost_usd REAL,
         files_read_before_edit INTEGER,
         errors_count INTEGER,
         outcome TEXT,
         timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
     );

   - Session detection logic:
     Group proxy_calls by project. A new session starts when there's
     a 10+ minute gap between calls OR the system prompt hash changes.
     The system prompt hash is more reliable than time alone.

   - turns_to_first_edit: count proxy_calls from session start until
     the first response containing a Write/Edit tool_use block.
     Parse the response body for tool_use with name matching
     Write|Edit|NotebookEdit.

   - exploration_cost_usd: sum cost_estimate_usd for all calls
     before the first edit.

   - Run this computation on ALL existing proxy_calls data
     (backfill from the 3,631 calls already logged).

2. ADD CLI command: engram proxy metrics
   - Show table of recent sessions grouped by enrichment_variant
   - Include averages: avg turns-to-first-edit, avg exploration cost
   - Compare baseline vs v1_slim side by side

3. TEST with existing data:
   engram proxy metrics

   Should show something like:
   Variant      Sessions  Avg Turns→Edit  Avg Explore $  Avg Total $
   baseline     XX        XX              $X.XX          $X.XX
   v1_slim      XX        XX              $X.XX          $X.XX

Context: This table is the feedback loop. Without it, we can't
prove enrichment works. The data already exists in proxy_calls —
this prompt structures it into measurable metrics.
```

### Acceptance Criteria
- session_metrics table exists with backfilled data
- `engram proxy metrics` shows comparison between variants
- turns-to-first-edit is computed correctly from tool_use parsing

### Dependency
- Prompt #01 must be done first (enrichment needs to be worth measuring)

---

## Session 3: Paired Experiment Runner

### Agent Instructions

```
Read these files first:
- docs/prompts/03-paired-experiment-runner.md (requirements)
- docs/prompts/plan.md (this file — strategic context)
- engram/proxy/metrics.py (session_metrics from prompt #02)

Do these things:

1. CREATE engram/experiment/runner.py
   Usage:
     engram experiment run \
       --task "fix the webhook validation" \
       --project monra-core \
       --cache-gap 300

   What it does:
   a) Creates two git worktrees from current HEAD
   b) CONTROL: spawns claude --message "<task>" with
      ANTHROPIC_BASE_URL pointing to proxy with --no-enrich
   c) Waits --cache-gap seconds (default 300) for cold cache
   d) ENRICHED: spawns claude --message "<task>" with
      ANTHROPIC_BASE_URL pointing to proxy with enrichment on
   e) Both runs use --max-turns 50 safety limit
   f) After both complete, queries session_metrics for comparison
   g) Prints side-by-side comparison
   h) Saves result to experiments table
   i) Cleans up worktrees

   Claude Code non-interactive: use `claude --message "..." --print`
   to pass a task and get output without interactive mode.

2. ADD CLI command: engram experiment run
   And: engram experiment results (show past experiments)

3. TEST with a simple task on the engram repo itself.

Context: This is the proof. If enrichment saves tokens and reduces
exploration, this runner will show it quantitatively. If it doesn't,
we'll know that too — and can iterate on the brief quality.
```

### Acceptance Criteria
- `engram experiment run --task "..." --project ...` executes two runs
- Comparison table printed with turns-to-first-edit delta
- Results stored for historical tracking

### Dependencies
- Prompt #01 (brief quality) — enrichment must be meaningful
- Prompt #02 (session metrics) — scoring must be automated

---

## Session 4+ (Future): Session Replay & Forward Simulation

After sessions 1-3 produce data:
- Replay completed sessions with opposite enrichment variant
- Forward simulation: predict which context variant wins before running
- See: docs/directions/engram-forward-simulation-roadmap.md

---

## How to Keep Continuity Between Sessions

Each session agent should:
1. Read this plan file FIRST for strategic context
2. Read the specific prompt file for detailed requirements
3. Check git log for what the previous session changed
4. Run tests before and after changes
5. Update this plan with results (mark sessions as done, add findings)

## Progress Tracker

- [ ] Session 1: Fix enrichment quality + Memgraph connection
- [ ] Session 2: Automated session metrics
- [ ] Session 3: Paired experiment runner
- [ ] Session 4: Session replay (future)
