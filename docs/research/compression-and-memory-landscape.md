# Compression & Memory Landscape — Research Notes

> **Date:** 2026-02-19 | **Sources:** Factory.ai benchmark, Noodlbox architecture analysis

---

## The Factory.ai Finding: Quality > Ratio

The core finding is deceptively simple: **compression ratio is the wrong metric.** OpenAI compressed sessions by 99.3%, Anthropic by 98.7%, Factory by 98.6% — almost identical ratios — but the quality scores diverged significantly:

| Method | Overall | Accuracy | Artifact Trail |
|--------|---------|----------|----------------|
| Factory | 3.70 | 4.04 | 2.45 |
| Anthropic | 3.44 | 3.74 | 2.33 |
| OpenAI | 3.35 | 3.43 | 2.19 |

The differences come from **how** they compress, not how much.

### Anchored Iterative Summarization (Factory's approach)

Factory maintains a **persistent structured summary** with dedicated sections (session intent, files modified, decisions made, next steps). When compression triggers, they **merge new information into that existing structure.** OpenAI and Anthropic regenerate the full summary from scratch each time, which causes gradual information drift across multiple compression cycles.

### The Concrete Example

After compressing an 89,000-token debugging session about a Redis/auth bug:

- **Factory's response:** correctly recalled the exact endpoint (`/api/auth/login`), error code (401), and root cause (stale Redis connection pool)
- **OpenAI's response:** "We were debugging an authentication issue. The login was failing for users."

All technical specificity gone. The compression ratio was nearly identical. The information preservation was not.

### The Key Principle

**Dedicated sections that force the summarizer to populate specific information categories rather than freeform prose.** This prevents silent information loss. Freeform summaries naturally drift toward vague generalizations across multiple compression cycles.

---

## The Unsolved Problem: Artifact Tracking

The most important finding for Engram: **artifact tracking is an unsolved problem.**

Even Factory's best-in-class structured approach only scored **2.45/5** on knowing which files were touched during a session. They call this out explicitly as needing specialized handling — a separate artifact index, or explicit file-state tracking outside of the summarization pipeline.

### Why This Matters for Engram

Engram already has the data to solve this. Every `tool_use` message with `Read`, `Edit`, `Write`, `Glob` contains the file path. Every `Bash` command contains the command and output. We can build an artifact index from existing session data — no new data collection needed.

### What an Artifact Trail Looks Like

For a given session, Engram could reconstruct:
```
Files read:     42 (monra-core/flow-service/src/handlers/*.ts, ...)
Files modified: 12 (specific list with line ranges)
Files created:   3 (new files)
Commands run:   58 (git, docker, curl, python, ...)
APIs called:     8 (Postgres queries, MCP tools)
Errors hit:      6 (with resolution status)
```

This is the **artifact trail** that compression destroys. If Engram maintains it separately from the compressed summary, it survives compression intact.

### Product Opportunity

If Engram can track what external resources an agent accessed during a session (files, API calls, tool outputs) and **preserve that through compression**, we'd be ahead of everyone in this space — including Factory's own product.

---

## Noodlbox Architecture — What Transfers

Noodlbox is a coding-only tool. It parses codebases into symbols, call graphs, dependency trees, and functional clusters — none of which exist outside of software.

**What doesn't transfer:** The specific implementation (AST parsing, symbol extraction, call graph construction). Can't run `noodl init` on a business process or document corpus.

**What does transfer as technique:**

1. **Knowledge graph + precise retrieval instead of context dumping** — the fundamental principle that you index first, then retrieve precisely, rather than stuffing everything into the context window. This applies to any domain.

2. **Community detection** — grouping related entities by functional relationships rather than file structure. For sessions, this means grouping memories by topic/decision rather than by chronological session.

3. **Impact detection** — knowing which parts of the knowledge base are affected by a change. For Engram, this means knowing which compressed memories become stale when new sessions add contradicting information.

4. **Pre-indexed context bundles** — shipping pre-analyzed context so agents don't re-discover the same information every session. For Engram, this is the "project brief" concept.

### Beyond Code — Future Direction

For non-dev contexts (fintech flows, accounting, construction bids), the analogous tool would be a knowledge graph over domain entities — invoices, tax rules, transaction types, counterparties — rather than code symbols. Nothing good exists here yet. Not something to build now, but a direction where Engram could evolve if it proves the session memory layer works.

---

## Implications for Engram's Compression Pipeline

### Immediate (buildable now)

1. **Structured compression format** — when Engram compresses sessions for CLAUDE.md injection, use dedicated sections:
   ```
   ## Session Intent
   [What the user was trying to accomplish]

   ## Decisions Made
   [Key architectural/implementation choices with rationale]

   ## Files Modified
   [Artifact trail — preserved separately from prose summary]

   ## Errors & Resolutions
   [Error→fix pairs with specifics preserved]

   ## Open Questions
   [Unresolved issues, next steps]
   ```

2. **Artifact index** — maintain a separate `artifacts` table in SQLite:
   ```sql
   CREATE TABLE artifacts (
       session_id TEXT,
       artifact_type TEXT,  -- file_read, file_write, command, api_call
       target TEXT,          -- file path, command string, API endpoint
       sequence INTEGER,     -- when in the session
       context TEXT           -- surrounding decision/error context
   );
   ```

3. **Impact-aware compression** — tag messages as `decision`, `exploration`, `error`, `fix`, `output` at index time. Compress differently per tag.

### Medium-term (needs embeddings)

4. **Relevance-gated injection** — score compressed memories against current query before injecting
5. **Cluster-based memory** — group observations by semantic topic rather than session timeline

### Long-term (needs validation)

6. **Anchored iterative summarization** — maintain persistent structured summaries that get merged into, not regenerated
7. **Cross-agent memory fusion** — combine Claude Code + Cursor + other agent sessions into unified project memory

---

## Benchmark Target

Factory.ai's scores provide a concrete benchmark:

| Metric | Factory (SOTA) | Engram Target |
|--------|---------------|---------------|
| Overall quality | 3.70/5 | 3.80+ |
| Accuracy | 4.04/5 | 4.10+ |
| Artifact trail | 2.45/5 | **3.50+** |

The artifact trail is where we can leapfrog — because we have the raw tool_use data that no one else is indexing.
