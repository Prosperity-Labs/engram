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
