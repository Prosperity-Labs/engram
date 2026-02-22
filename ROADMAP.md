# Engram Roadmap

> **Last Updated:** 2026-02-22

## Shipped (v0.1.0)

- [x] SQLite session store with FTS5 full-text search
- [x] LiveIndexer — incremental JSONL polling with byte-offset tracking
- [x] Terminal monitor with sparklines, role/tool breakdown
- [x] `engram install` — bulk index all existing sessions
- [x] `engram search` — ranked search with highlighted snippets
- [x] `engram monitor --watch` — live dashboard

## Shipped (v0.2.0)

- [x] Clean project name parsing (filesystem-aware, dot-encoding support)
- [x] `engram stats` — per-project analytics (token cost, error rate, tool usage)
- [x] `engram sessions` — list sessions with filtering by project, date, size
- [x] Export to JSON/CSV for external analysis
- [x] `engram artifacts --extract` — artifact extraction from tool calls
- [x] `engram clean-names` — batch project name normalization
- [x] `engram reindex` — full reindex command
- [x] 3 agent adapters: Claude Code, Codex, Cursor
- [x] FTS5 query sanitizer for special characters
- [x] 70 tests, 11 CLI commands

## Shipped (v0.3.0)

- [x] `engram brief` — auto-generates CLAUDE.md from session history
  - `_project_overview()` — session count, messages, tokens, cost, date range
  - `_key_files()` — most-read + most-modified files from artifacts table
  - `_architecture_patterns()` — FTS5 search for decision keywords
  - `_common_errors()` — recurring errors grouped from artifacts
  - `_cost_profile()` — exploration/mutation/execution % with recommendations
  - `generate_brief()` — assembles markdown or JSON (target: 500-2000 tokens)
- [x] CLI: `engram brief --project <name> [--format json] [--output CLAUDE.md]`
- [x] 4 benchmarks validated against 13,881 real artifacts:
  - Artifact completeness: 89.1% (target >80%)
  - Context recovery: 100% (target >60%)
  - Token savings: 64% (target >50%)
  - Search precision: 89% (target >70%)
- [x] Benchmark runner: `benchmark/run_benchmarks.py`
- [x] Real data benchmarks with synthetic CI fallback
- [x] Multi-agent build: Codex (brief.py), Cursor (CLI + benchmarks), Claude Code (specs, review, merge)
- [x] 91 tests, 12 CLI commands

---

## Shipped (v0.4.0) — Two-Layer Context Injection

> The problem with injecting everything into CLAUDE.md: it's read at session start and consumes context window immediately. For short sessions or simple tasks, that's pure waste. The brief was designed to be curated (500-2000 tokens), but even that is blunt — same content regardless of what the session is about.
>
> The fix: split static background knowledge from just-in-time file context.

### Layer 1: Slim CLAUDE.md (<500 tokens)
- [x] Trim `generate_brief()` output to only dangerous knowledge:
  - Co-change clusters (the 5 files that always break together)
  - High error-ratio files (endpoints.ts: 40:1 error/write across 15 sessions)
  - Load-bearing architecture decisions (the ones that keep causing regressions)
- [x] `engram brief --slim` flag for the compact output
- [x] Always-on background knowledge — worth the token cost every session

### Layer 2: PreToolUse Hook — Just-in-Time Injection
- [x] Claude Code hook: fires before Read/Edit tool calls
- [x] Queries artifacts table by file path being touched
- [x] Injects one-liner context when the agent is about to touch a file with history:
  ```
  # endpoints.ts — 40:1 error/write ratio, 15 sessions. Last error: "CORS header missing" (2026-02-19)
  ```
- [x] ~20 tokens per injection, zero cost when file has no history
- [x] New module: `engram/hooks.py` — hook handler + artifact lookup
- [x] `engram hooks install` — writes Claude Code hook config to `~/.claude/settings.json`

### Data layer (already exists)
- `_key_files()` → data source for Layer 1
- `_common_errors()` → data source for Layer 1
- artifacts table → data source for Layer 2 file lookups
- No new schema needed — just new query patterns on existing tables

### Known Bugs
- [x] ~~Slim brief "Danger Zones" shows raw JSON instead of file paths~~ — fixed by correlating errors to files via session co-occurrence instead of matching error targets directly.
- [ ] **Recurring Errors section shows raw JSON tool_use content.** Root cause: `ArtifactExtractor` stores `content[:200]` as `error.target` instead of extracting the actual error message. Fix belongs in `artifact_extractor.py`.

### Improvements Needed
- [ ] **Key Decisions pulls noise instead of real architecture decisions.** `_architecture_patterns()` uses keyword search ("chose", "decided", "because") which matches user messages, system prompts, and plan mode boilerplate. Needs: (a) filter to `role=assistant` only, (b) minimum content length, (c) exclude known boilerplate patterns like "Entered plan mode", "/compact".
- [ ] **Slim brief filenames lose context.** `handlers.ts` appears in both monra-core and api-gateway. Short names are compact but ambiguous when a project has multiple services. Consider showing `flow-service/.../handlers.ts` or at least the parent dir.
- [ ] **Danger zone ratios are inflated.** 78:1 error/write means 78 errors happened in the same *session* as 1 write — not 78 errors *caused by* that file. The session-level correlation overestimates danger for files edited in error-heavy sessions. Consider narrowing to errors within N sequence numbers of the write.
- [ ] **Full brief paths should also be shortened.** Full absolute paths waste tokens. Apply the same `Path.name` or relative-path treatment as slim brief.
- [ ] **`last_session_summary()` shows engram's own files.** The last monra-app session was actually an engram session that happened to be grouped under monra-app. Need project filtering that's more precise.

### Benchmark: Hook Effectiveness
- [ ] New benchmark: of files the agent re-reads, how many had prior history available?
- [ ] Measure: does the hook reduce re-reads in subsequent sessions?

### Auto-Indexing
- [ ] `engram install` must be run manually before hooks have data — UX gap
- [ ] Options: SessionStart hook runs `engram install`, lazy index in pretool.sh, background daemon
- [ ] Goal: zero-setup — install hooks once, everything stays fresh automatically

---

## Phase 3 — Model-Agnostic Loop Instrumentation

> Every agent — Claude Code, OpenCode, Codex, Cursor, any open source agent — runs the same loop: **Think → Act → Observe → Repeat**. There are no forking DAGs. There is no complex orchestration graph. It's a flat loop, and the only place to instrument it without disrupting the agent is at the **Observe** step — after the tool runs, before the next Think.

Engram becomes the universal Observe layer.

### The TAOR Loop

```
┌──────────┐     ┌──────────┐     ┌──────────────────┐     ┌──────────┐
│  Think   │────▶│   Act    │────▶│     Observe      │────▶│  Repeat  │
│ (reason) │     │ (tool)   │     │ (Engram hooks in │     │ (next    │
│          │     │          │     │  here — indexes,  │     │  turn)   │
│          │     │          │     │  tracks, enriches)│     │          │
└──────────┘     └──────────┘     └──────────────────┘     └──────────┘
```

### What "hooking at Observe" means
- [ ] Intercept tool results before they flow back into the agent's context
- [ ] Index artifacts (files touched, commands run, errors hit) in real-time
- [ ] Inject relevant prior knowledge when the agent is about to re-discover something
- [ ] Track what the agent *actually did* vs what it *intended* — across compression boundaries

### Why the runtime isn't a DAG (but the knowledge model can be)
Agent runtimes don't fork into parallel execution graphs. Even "multi-agent" setups (Codex + Cursor + Claude Code on the same feature) are independent TAOR loops that happen to share a filesystem. The coordination layer is git, not a DAG scheduler. Engram instruments each loop independently.

However, the **knowledge extracted** from observing these loops *does* form a graph — decisions that led to errors, files that triggered test failures, architecture choices that constrained later sessions. The runtime is a flat loop; the memory built from it is a DAG of causality and context.

### Runtime adapters
- [ ] Claude Code — JSONL session log polling (shipped in v0.1.0, the foundation)
- [ ] OpenCode — adapter for its session format
- [ ] Codex — adapter (started in v0.2.0)
- [ ] Cursor — `.specstory` adapter (started in v0.2.0, hooks not wired yet)
- [ ] Generic agent — stdin/stdout hook for any TAOR loop that emits tool calls

### Build after: v0.3.0 benchmarks prove the value of session memory.

---

## Future Features

### Artifact Trail Index (mostly shipped — v0.2.0 + v0.4.0)

Maintain a separate artifact index that survives compression. Factory.ai's benchmark shows artifact tracking scores 2.45/5 even for SOTA — this is the gap Engram can fill.

**Status:** Core shipped. Schema, extractor, CLI commands, and hook queries all working. Remaining: time-based filtering (`--recent 7d`), error target cleanup, error-to-fix resolution linking.

**What it tracks:**
- [x] Files read/written/created (extracted from Read, Edit, Write, Glob tool calls)
- [x] Commands executed (Bash tool calls)
- [x] API calls made (MCP tools, curl commands)
- [ ] Errors encountered and their resolution status (extraction works, but targets store raw JSON — needs cleanup)

**Schema:**
```sql
CREATE TABLE artifacts (
    session_id    TEXT,
    artifact_type TEXT,   -- file_read, file_write, file_create, command, api_call, error
    target        TEXT,   -- file path, command, endpoint
    sequence      INTEGER,
    context       TEXT    -- surrounding decision/error context
);
```

**Commands:**
```
engram artifacts --session <id>
engram artifacts --project monra --type file_write
engram artifacts --recent 7d
```

**Why this matters:** When compression discards 98% of tokens, the artifact trail tells you *what actually happened* — which files changed, what commands ran, what broke. No one else preserves this through compression.

**Build after:** v0.2.0. Data already exists in indexed messages — just needs extraction.

See: [docs/research/compression-and-memory-landscape.md](docs/research/compression-and-memory-landscape.md)

---

### Replay Engine (Phase 2 — deterministic replay & experience extraction)

Record agent execution traces, reconstruct execution trees, and replay from any fork point with modified context. Academic validation (AgentRR, arxiv 2505.17716) confirms multi-level experience abstraction from recorded traces. Market validation from Vellum/Rely Health shows 100x issue resolution improvement in production healthcare agents.

**Engram's advantage:** Claude Code already writes full execution traces to JSONL — no SDK instrumentation required. The record layer is done; replay and experience abstraction are what's left.

**Why it matters beyond debugging:** Deterministic replay is a governance and compliance primitive, not just a developer tool. Enterprise buyers need post-incident forensics and operational assurance for AI agents.

**Requirements (sequential):**
1. ~~Artifact manifest~~ (being built now)
2. ~~Session JSONL parsing~~ (done)
3. Execution tree reconstruction from artifact sequence
4. Fork point UI — select any node, branch from there
5. Context injection at fork point
6. Parallel run comparison (same task, different model/context)

**Build after:** v0.3.0 benchmarks prove value; artifact manifest is solid.

See: [docs/research/replay-engine-market-validation.md](docs/research/replay-engine-market-validation.md)

---

### Structured Compression (Factory.ai-inspired)

Replace freeform session summaries with anchored iterative summarization — dedicated sections that get merged into, not regenerated from scratch.

**Format:**
```
## Session Intent
[What the user was trying to accomplish]

## Decisions Made
[Key choices with rationale — preserved with full specificity]

## Artifacts
[Files, commands, APIs — from the artifact index]

## Errors & Resolutions
[Error→fix pairs with exact error codes and endpoints]

## Open Questions
[Unresolved issues, next steps]
```

**Key principle:** Dedicated sections force population of specific categories. Freeform prose drifts toward vague generalizations across compression cycles.

**Benchmark target:** Factory scores 4.04/5 accuracy. Engram target: 4.10+ by combining structured format with artifact preservation.

**Build after:** artifact trail index exists.

See: [docs/research/compression-and-memory-landscape.md](docs/research/compression-and-memory-landscape.md)

---

### Cost Intelligence Recommendations (partially shipped — v0.2.0 + v0.3.0)

**Status:** Exploration/mutation/execution ratios shipped in `_cost_profile()` (v0.3.0) and `engram stats` (v0.2.0). >30% exploration warning shipped in full brief. Remaining: dedicated `engram cost` commands with per-session recommendations.

When Engram detects >30% of session tokens spent on file exploration (glob, grep, read patterns), recommend retrieval layer integration (e.g. Noodlebox/MCP).

**How it works:**
1. Analyze tool call distribution per session
2. Classify tools into categories: exploration (Glob, Grep, Read), mutation (Edit, Write), execution (Bash), search (MCP tools)
3. Flag sessions where exploration dominates — the agent is spending tokens *finding* code instead of *working on* code
4. Recommend specific interventions: "This project would save ~40% tokens with a code index MCP server"

**Commands:**
```
engram cost analyze --project monra
engram cost recommend
```

**Example output:**
```
Project: monra-app (12 sessions, 145M tokens)

  Exploration:  36%  ████████░░░░░░░░  (Glob: 29, Grep: 59, Read: 159)
  Mutation:     22%  █████░░░░░░░░░░░  (Edit: 122, Write: 31)
  Execution:    42%  ██████████░░░░░░  (Bash: 291)

  ⚠ High exploration ratio (36%) — consider adding a retrieval
    layer (Noodlebox, code search MCP) to reduce file discovery cost.
    Estimated savings: ~25M tokens across future sessions.
```

**Build after:** v0.2.0 stats infrastructure.

---

### Git Integration

`engram search` returns relevant sessions AND correlates them with actual git history — closing the gap between "what we discussed" and "what we shipped."

**What it adds to search results:**
- Which commits touched the searched files
- What actually changed (diff) vs what was planned (session intent)
- Commit ↔ session linking via timestamps and file overlap

**Commands:**
```
engram search "deposit flow" --git     # search results enriched with commit context
engram diff --session <id>             # what shipped vs what was discussed
engram trail --file src/deposits.py    # session history + git history interleaved
```

**Example output:**
```
Session abc123 (2026-02-18, monra-core)
  Intent: "Fix deposit webhook retry logic"
  Files discussed: src/deposits/webhook.py, src/deposits/retry.py

  Linked commits:
    a1b2c3d  fix: handle duplicate webhook events  (2h after session)
    d4e5f6g  test: add webhook retry integration tests

  Drift: session discussed adding exponential backoff,
         but commit only added dedup check — backoff not shipped.
```

**Why this matters:** Sessions capture intent and reasoning. Git captures what actually happened. Neither alone tells the full story. Together they answer: "Did we actually ship what we discussed? What fell through the cracks?"

**Build after:** v0.2.0. Requires artifact trail index for file-level session↔commit matching.

---

### Architectural Knowledge Extraction

Analyze sessions across a project to extract implicit architectural knowledge — sequence diagrams, verification rules, invariants, dependency maps.

**Data sources:**
- Engram session graph
- Recurring tool call sequences
- Error→fix chains across sessions

**Commands:**
```
engram architecture analyze --project monra
engram architecture show --flow deposit
engram architecture show --invariants
```

**Build after:** benchmark proven, first external users.

---

### Cross-Agent Memory (.specstory integration)

Ingest Cursor sessions from `~/.specstory` alongside Claude Code sessions into the same Engram database.

**Goal:** reconstruct full project architectural understanding from both Claude Code + Cursor sessions combined — without anyone manually documenting anything.

**Command:**
```
engram import --source specstory --path ~/.specstory
```

**Build after:** architectural extraction layer exists.

---

### claude-mem Knowledge Graph Bootstrap

claude-mem has existing structured observations about projects. Import these as the seed layer of the Engram knowledge graph so it starts populated rather than empty.

**Steps:**
1. Parse claude-mem observation format
2. Map to Memgraph schema:
   - File observations → File nodes
   - Pattern observations → Concept nodes
   - Error observations → Error nodes
   - Workflow observations → Decision chains
3. Tag imported nodes: `source="claude-mem"`
4. Engram sessions build on top of this foundation

**Command:**
```
engram import --source claude-mem
```

**Build alongside:** Memgraph integration.

---

## Research: Smart Memory Techniques

*Inspired by Noodlbox's architecture and Factory.ai's research on agent memory.*

### 1. Relevance-Gated Context Injection

**Problem:** Current compression (CLAUDE.md, session summaries) is all-or-nothing — the full summary gets injected regardless of whether it's relevant to the current turn.

**Approach:** Before injecting compressed memory, score it against the current query using FTS5 or embeddings. Only inject the fragments that are semantically relevant.

**Example:** If the user asks about "deposit webhooks", don't inject memories about KYB fixes or escrow testing. Only inject the deposit-related observations.

**Implementation:**
1. Compress session history into tagged fragments (not one big blob)
2. At injection time, run `engram search` against the current user message
3. Inject top-K relevant fragments as system context
4. Track which fragments get used (do they reduce errors? do they save exploration?)

**Buildability:** Medium. FTS5 already does the relevance scoring. The hard part is integrating with Claude Code's context injection pipeline (hooks or CLAUDE.md generation).

---

### 2. Cluster-Based Memory Structure

**Problem:** Session summaries are chronological — "first we did X, then Y, then Z." But knowledge is topical — "everything about the auth module" spans 15 sessions over 3 weeks.

**Approach:** Group observations by semantic cluster rather than by session timeline. Similar to how Noodlbox groups code by functional communities, group memories by topic.

**Implementation:**
1. Extract key observations from each session (decisions, errors, patterns)
2. Cluster observations using embeddings (e.g. "auth" cluster, "deposit flow" cluster, "deployment" cluster)
3. Compress per-cluster rather than per-session
4. Result: `engram recall --topic auth` returns a coherent summary of all auth-related decisions across all sessions

**Research basis:** Factory.ai shows structured summaries significantly outperform naive truncation on agent continuation tasks.

**Buildability:** Medium-high. Requires embeddings (ChromaDB or local model). The clustering is the research-heavy part.

---

### 3. Impact-Aware Compression

**Problem:** Not all context is equal. Some past decisions are load-bearing for current reasoning ("we chose JWT over sessions because X"), others are historical noise ("we ran 15 grep commands looking for a file").

**Approach:** Track which past context actually influences future decisions vs. which is safely forgettable. Compress aggressively on noise, preserve signal.

**Signals for load-bearing context:**
- Decisions that get referenced later ("as we decided earlier...")
- Error→fix pairs (the fix is valuable, the debugging chain is not)
- Architecture choices that constrain future work
- Configuration values and environment specifics

**Signals for noise:**
- File exploration chains (Glob→Read→Grep→Read loops)
- Failed attempts that were abandoned
- Verbose tool output (full file contents, long command output)

**Implementation:**
1. Tag messages at index time: `exploration`, `decision`, `error`, `fix`, `output`
2. Compress differently per tag: decisions get full preservation, exploration gets 1-line summary
3. Natural breakpoints for compression: tool result boundaries, user turn boundaries

**Buildability:** High — this is the most immediately actionable one. The tagging can be rule-based (tool_name patterns) without needing ML.

---

### 4. Pre-Analyzed Context Bundles

**Problem:** Every new session re-discovers the same project structure. The first 10-20 messages of every session are "read the config, understand the layout, find the entry point" — pure waste.

**Approach:** Ship pre-built project profiles that give the agent a head start. Like Noodlbox shipping pre-indexed context for popular packages.

**Two levels:**
1. **Per-project bundles** — Engram analyzes your past sessions for a project and generates a compact "project brief" that can be injected into CLAUDE.md:
   ```
   engram brief --project monra > CLAUDE.md
   ```
   Output: key files, architecture overview, common patterns, known gotchas — all extracted from session history.

2. **Community bundles** — Pre-built profiles for common stacks (Next.js + Prisma, FastAPI + SQLAlchemy, etc.) that encode typical tool patterns and cost profiles.

**Buildability:** Level 1 is very buildable — it's essentially `engram search` + summarization. Level 2 needs community/marketplace infrastructure.
