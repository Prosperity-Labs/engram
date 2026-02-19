# Engram Roadmap

> **Last Updated:** 2026-02-19

## Current (v0.1.0)

- [x] SQLite session store with FTS5 full-text search
- [x] LiveIndexer — incremental JSONL polling with byte-offset tracking
- [x] Terminal monitor with sparklines, role/tool breakdown
- [x] `engram install` — bulk index all existing sessions
- [x] `engram search` — ranked search with highlighted snippets
- [x] `engram monitor --watch` — live dashboard

## Next (v0.2.0)

- [ ] Clean project name parsing (strip `-home-prosperitylabs-Desktop-...` prefixes)
- [ ] `engram stats` — per-project analytics (token cost, error rate, tool usage)
- [ ] `engram sessions` — list sessions with filtering by project, date, size
- [ ] Export to JSON/CSV for external analysis

---

## Future Features

### Cost Intelligence Recommendations

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
