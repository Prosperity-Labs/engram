# Engram Architecture

> **Why this document exists:** Engram's design makes choices that aren't obvious from the code alone. This doc explains the reasoning so contributors and users understand not just *what* it does, but *why* it's built this way.

---

## The Problem

Long-running AI agent sessions generate hundreds of messages and thousands of tokens. No model holds that indefinitely. When context fills up, agents compress — and compression destroys exactly the information agents need most:

- Which files did I already modify?
- What was the actual error message?
- Why did we choose this approach over the alternative?

Every existing tool treats this as a summarization quality problem. **Engram treats it as an architecture problem.**

---

## The Benchmark

Factory.ai published the most rigorous evaluation of agent compression to date — 36,000+ messages across production software engineering sessions. Their results set the baseline Engram is designed to beat:

| Method | Overall | Accuracy | Artifact Trail |
|--------|---------|----------|----------------|
| Factory (SOTA) | 3.70/5 | 4.04/5 | 2.45/5 |
| Anthropic native | 3.44/5 | 3.74/5 | 2.33/5 |
| OpenAI native | 3.35/5 | 3.43/5 | 2.19/5 |

**Artifact trail** — knowing which files the agent touched — scores below 2.5 for *everyone*, including Factory's best-in-class approach. Factory calls this out explicitly as an unsolved problem requiring specialized handling outside the summarization pipeline.

**Engram's targets:**

| Metric | Factory (SOTA) | Engram Target |
|--------|---------------|---------------|
| Overall quality | 3.70/5 | 3.80+ |
| Accuracy | 4.04/5 | 4.10+ |
| **Artifact trail** | **2.45/5** | **4.50+** |

The artifact trail target is aggressive because Engram doesn't try to summarize artifact information better. It removes artifacts from the summarization problem entirely.

---

## The Core Insight: Two Separate Problems

Factory's ceiling of 2.45/5 on artifact tracking is a **category error**, not a quality problem.

They ask an LLM to remember which files it touched — buried in a freeform summary, competing with everything else for attention, re-summarized across multiple compression cycles. That's inherently lossy. The solution isn't better summarization. It's recognizing that artifact tracking and decision preservation are fundamentally different problems requiring different tools.

**Artifacts** (files touched, commands run, APIs called) are deterministic facts. They live in `tool_use` blocks. They can be extracted with certainty, accumulated verbatim, and preserved without any LLM involvement.

**Decisions** (why we chose JWT, why we refactored the handler) live in conversation prose. They need structured compression — but compression where the LLM is forced to populate explicit sections rather than write freeform summaries.

---

## The Two-Layer Architecture

```
Agent session (any agent)
        ↓
  AgentAdapter
  (normalizes to EngramSession)
        ↓
  EngramSession
        ↓
  ┌─────────────────┬──────────────────────┐
  │  Artifact        │  Decision Log         │
  │  Manifest        │  (Structured          │
  │  (Layer 1)       │  Compression)         │
  │                  │  (Layer 2)            │
  └─────────────────┴──────────────────────┘
```

| Layer | What it holds | How it persists | Needs LLM? |
|-------|--------------|-----------------|------------|
| **Artifact Manifest** | What happened — files, commands, APIs, errors | Deterministic extraction from `tool_use` blocks, accumulated verbatim, never summarized | **No** |
| **Decision Log** | Why it happened — choices, rationale, constraints | Structured compression with dedicated sections, merged not regenerated | Yes |

When compression triggers, both layers are injected — the manifest verbatim, the decision log as structured prose. The agent always knows what it touched (manifest) and why decisions were made (log). Neither competes with the other for attention.

---

## Layer 1: Artifact Manifest

### What gets tracked

```
Session: 82b957bc  |  Agent: cursor  |  Duration: 2h 14m

FILES MODIFIED (12):
  monra-core/flow-service/src/handlers/claim-link-transfer.ts  [Edit ×3]
  monra-core/web3-service/src/lib/utils/constants.ts           [Edit ×1]
  monra-core/flow-service/src/listeners/webhook-processor.ts   [Edit ×2]

FILES READ (42):
  monra-lib/src/lib/clients/database/types.ts                  [Read ×4]

COMMANDS (58):
  docker logs flow-service --tail 50                           [×12]
  git diff --cached                                            [×3]
  curl -X POST localhost:3001/api/...                          [×5]

ERRORS (6):
  "Insufficient balance" → RESOLVED: added balance check before claim
  "CDK no changes detected" → RESOLVED: cleared .cdk.staging cache

DECISIONS:
  - Chose event-driven claim over polling (latency requirement)
  - Added escrow detection to Alchemy webhook (prevent double-credit)
```

### SQLite schema

```sql
CREATE TABLE artifacts (
    id          INTEGER PRIMARY KEY,
    session_id  TEXT NOT NULL,
    agent       TEXT NOT NULL,
    type        TEXT NOT NULL,  -- file_read | file_write | command | api_call | error | error_resolved
    target      TEXT NOT NULL,  -- file path, command string, API endpoint
    detail      TEXT,           -- edit count, error message, resolution
    sequence    INTEGER,        -- position in session
    timestamp   TEXT
);
```

### How it's populated (by agent)

**Cursor:** `afterFileEdit` hook fires in real time as each file changes. Most accurate source — files recorded as they're touched, not inferred after the fact.

**Claude Code:** `SessionEnd` hook parses JSONL, extracting all `tool_use` blocks with types `Read`, `Edit`, `Write`, `Bash`, `Glob`.

**Codex:** `agent-turn-complete` notify event + `~/.codex/history.jsonl` parsing. Extracts `command_execution` and `file_changes` event types.

### The rule: manifest is never compressed

When compression triggers, the full manifest is injected verbatim. It appends — it never gets summarized. A session that ran for 8 hours with 500 file reads produces a manifest that accurately reflects all 500 reads, no matter how many compression cycles occur.

---

## Layer 2: Decision Log (Structured Compression)

### Why freeform fails

Factory showed that freeform summarization drifts toward vague generalizations across compression cycles. Each regeneration loses detail. After 3-4 compression events, summaries become useless — correct at a high level, empty of specifics.

The fix isn't smarter prompts. It's **structure that forces preservation**.

When you mandate that a summary must populate `## Files Modified` with specific paths, it cannot silently drop them. The section acts as a checklist. Empty means explicitly empty, not forgotten.

### Compression format

```markdown
## Session Intent
[One sentence: what the user was trying to accomplish]

## Decisions Made
[Key choices with rationale — "chose X over Y because Z"]

## Errors & Resolutions
[Specific error messages and what fixed them]

## Current State
[Where work stands right now]

## Next Steps
[Unresolved issues, what to tackle next]
```

### Anchored iterative merging

Rather than regenerating the full summary each compression cycle, Engram merges:

1. On first compression: generate the structured summary from the session span being dropped
2. On subsequent compressions: merge the new span's summary into the existing structured summary section by section

This preserves decisions from early in a session even after 10+ compression cycles. Factory's approach does something similar — it's why they score 0.35 points higher than OpenAI overall.

---

## Multi-Agent Support

Engram normalizes all agent sessions to a single `EngramSession` format before any processing. The manifest writer, compression pipeline, inspector, and replay engine never know which agent ran the session.

```python
class AgentAdapter:
    def parse(self, raw) -> EngramSession: ...

class ClaudeCodeAdapter(AgentAdapter): ...  # reads ~/.claude/ JSONL
class CursorAdapter(AgentAdapter):     ...  # reads hook events + transcripts
class CodexAdapter(AgentAdapter):      ...  # reads ~/.codex/history.jsonl
```

`engram install` auto-detects which agents are installed and wires the appropriate hooks. Users who switch between agents, or use multiple agents on the same project, get unified session history with no configuration.

**Why this matters strategically:** Anthropic can build memory natively into Claude Code. OpenAI can do the same for Codex. Neither can build the cross-agent layer — that requires sitting outside all of them. Engram's agent-agnostic architecture is a moat neither can individually close.

---

## Replay Engine

The replay engine is built on top of the artifact manifest. This is why the manifest caches tool output hashes — they become the replay cache.

```
fork(session_id, node_id)
  → creates ReplaySession from EngramSession
  → pre-fork tool calls served from manifest cache (zero API cost)
  → post-fork runs normally with new variable

diff(original, replayed)
  → structured comparison of outputs
```

**Works for any agent.** A forked Cursor session replays Cursor file edits from the manifest. A forked Codex session replays Codex command executions. The `EngramSession` abstraction means the replay engine is identical regardless of source agent.

---

## Data Storage

All Engram data lives in `~/.engram/`:

```
~/.engram/
├── engram.db              # SQLite — sessions, artifacts, decisions
├── manifests/
│   └── {session_id}.json  # verbatim artifact manifests
└── logs/
    └── install.log
```

No external infrastructure required. No Docker. No cloud. `pip install engram && engram install` is the entire setup.

Optional extensions (not in core):
- `engram-graph` — ChromaDB + Memgraph for semantic recall and knowledge graph queries
- `engram-cloud` — session sync across machines (future)

---

## What Engram Is Not

**Not a logging tool.** Logs record everything. Engram decides what to preserve and how.

**Not a smarter CLAUDE.md.** CLAUDE.md is one possible output — a view over the database, not the database itself.

**Not another LangSmith.** LangSmith observes. Engram observes, compresses, tracks artifacts, and replays. The feedback loop from session end to next session start is the product.

---

## Benchmark Methodology

When Engram's artifact trail claims are validated, the evaluation should use Factory.ai's probe methodology:

- **Recall probes:** "What was the original error message?"
- **Artifact probes:** "Which files have we modified? Describe what changed in each."
- **Continuation probes:** "What should we do next?"
- **Decision probes:** "What did we decide about the Redis configuration?"

Graded across: Accuracy, Context awareness, Artifact trail, Completeness, Continuity, Instruction following (0-5 each).

Factory's published rubrics are the standard. Engram's artifact trail score should be measured against them once a test dataset exists.

---

## Build Order

1. `AgentAdapter` + `EngramSession` — normalize all sessions to one format
2. `ClaudeCodeAdapter`, `CursorAdapter`, `CodexAdapter` — wire all three agents
3. Artifact Manifest — file paths first, then commands, then APIs
4. Structured Compression — section-based decision log, iterative merging
5. Manifest + log injection on compression trigger
6. `ReplayEngine` — fork, mock pre-fork tools from manifest, diff
7. Batch regression — apply changes across N sessions, score with LLM judge
8. Simulation — swap model, prompt, or context on any past session

---

*Last updated: February 2026*
*Benchmark reference: Factory.ai — "Evaluating Context Compression for AI Agents", December 2025*
