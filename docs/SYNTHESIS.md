# The Synthesis — Self-Improving Coding Agents

> Written: 2026-02-23
> Status: Vision document — the pieces exist, they're not connected yet

## The Insight

We kept building pieces without seeing they form a whole:

**OpenClaw** records what each agent did across worktrees. That's **state**.

**Engram** tracks which changes produced working code vs burn sessions. That's **outcome**.

**Replay** lets you fork at a decision point and try a different path. That's **simulation**.

Put those three together: an agent that looks at its own history, identifies decision
points where sessions went wrong, simulates alternative paths, runs them autonomously
in isolated worktrees, and learns which strategies work on your specific codebase.

**That's not just observability. That's a coding agent that gets smarter from its own
failures. Continuously. On your codebase specifically.**

## Honest Competitive Assessment (researched Feb 23, 2026)

Some competitors have **parts** of this loop. Nobody has the full thing for local coding agents.

| Competitor | What they have | Overlap with us | What they're missing |
|-----------|---------------|----------------|---------------------|
| **LangGraph** | Time-travel: checkpoint-based state replay, fork/branch at decision points, alternative path exploration | **Direct overlap with our Simulation layer** | Only works for LangChain-based agents. No file-change tracking. No cross-session learning. |
| **Devin** | Session memory, repo notes, learns from failures, recalls context | **Partial overlap with Outcome + Learning** | Closed ecosystem. Cloud-only. No local worktree execution. No audit trail for compliance. |
| **Proliferate** | Cloud sandboxes, reactive execution from Sentry/Linear triggers | Execution overlap | Cloud sandboxes, not local worktrees. No session history analysis. No replay. |
| **Langfuse** | LLM traces, Claude Code integration (via template) | Traces conversations | Only traces what the LLM *said*, not what files changed. No simulation, no learning loop. |
| **Braintrust** ($80M) | LLM evaluation, tracing, scoring | Observability overlap | No file-change tracking, no replay, no coding-agent-specific features. |
| **AgentOps** | Agent monitoring, session replay | Monitoring overlap | No file-change tracking at artifact level, no fork/simulate. |
| **Claude-mem / chad** | AI-curated observations, vector search | History overlap | No execution, no simulation, no file-level audit. |
| **Noodlbox** | Codebase knowledge graph (static) | Understanding overlap | No runtime behavior data, no session tracking. |

### What's actually unique

The claim "nobody has all four pieces" needs qualification:

- **LangGraph has simulation** (time-travel/forking) — but only for LangChain agents, not Claude Code/Codex/Cursor
- **Devin has learning** (session memory, failure recall) — but it's a closed cloud product, not an observability tool
- **Nobody has file-level artifact extraction** from local coding agent sessions (16,303 artifacts from real JSONL)
- **Nobody has local worktree-based parallel agent execution** with a live dashboard tracking what each one does

### The actual gap

**Coding agent audit trails for local development** — the intersection of:
1. Deterministic file-change tracking (not just LLM traces)
2. Multi-agent coordination visibility (which agent touched what)
3. Compliance-grade audit trail (SOC2, EU AI Act)
4. Works with ANY coding agent (Claude Code, Codex, Cursor — not locked to one framework)

This is the gap Proliferate doesn't fill (they're cloud sandboxes), LangGraph doesn't fill (they're LangChain-only), and Devin doesn't fill (they're a closed product, not an observability tool).

## Proliferate vs OpenClaw Analysis

**Proliferate** (YC-backed): Cloud sandboxes that spin up from Sentry/Linear triggers. Reactive execution.

**OpenClaw**: Local worktree-based parallel agent execution with live dashboard.

| Dimension | Proliferate | OpenClaw |
|-----------|------------|---------|
| Where agents run | Cloud sandboxes | Local git worktrees |
| Trigger model | Reactive (Sentry/Linear events) | Developer-directed |
| Multi-agent visibility | Limited | 3-lane live dashboard |
| File-change tracking | Sandbox-scoped | Cross-session artifact extraction |
| Audit trail | Cloud logs | Local JSONL + SQLite (16K+ artifacts) |
| Compliance | Cloud provider dependent | Full local audit trail |
| Replay/simulation | Not built | Scaffolded (visual replay working) |
| Learning loop | Not built | Outcome layer exists (Engram) |

**Key insight**: Nobody is doing local worktree-based parallel agent execution with a live
dashboard tracking what each one does. That's the gap.

## What We've Already Built

### 1. State Layer — OpenClaw Dashboard (:8789)
- Real-time SSE streaming of multi-agent events
- 3-lane view: Claude (purple), Codex (orange), Cursor (cyan)
- File tree showing which agent touched what
- Replay mode with timeline scrubber and speed controls (0.5x-10x)
- Gource + Excalidraw export
- Run detection (clusters events by 60s gaps)
- **276 events captured**, Express.js + JSONL storage

### 2. Outcome Layer — Engram (pip installable)
- **16,303 artifacts** deterministically extracted from 290 sessions
- Artifact types: file_read (4,295), file_write (1,641), file_create (829), command (6,619), error (2,179), api_call (740)
- Cross-session intelligence:
  - Danger zones: files with high error-to-write ratios
  - Co-change clusters: files that always modify together
  - Burn session detection: high cost, zero output
  - Hotspot files: excessively rewritten by agents
  - Sensitive file access: .env, credentials, infra configs
- 3 agent adapters: Claude Code, Codex, Cursor
- SQLite + FTS5, 12 CLI commands, 91 tests

### 3. Simulation Layer — Replay Engine (scaffolded)
- Research validated by AgentRR (arxiv), Microsoft debug-gym, Vellum/Rely Health
- Demo HTML exists (`personal-knowledge-graph/replay-demo.html`)
- Dashboard replay already works for event playback
- Replay roadmap on taskboard (Days 19-23)
- Missing: fork-point detection, isolated worktree execution, A/B comparison

### 4. Taskboard — Agent Orchestration (:8788)
- 46 tasks tracked across v0.1.0 → v0.3.0
- Agent assignment (Claude, Codex, Cursor, Validator)
- Multi-agent pipeline coordination
- JSON API at `/api/tasks`

## The Loop That Doesn't Exist Yet

```
                    ┌──────────────────────────────┐
                    │                              │
    ┌───────────────▼───────────────┐              │
    │  RECORD (OpenClaw + Engram)   │              │
    │  Agent runs, artifacts logged │              │
    └───────────────┬───────────────┘              │
                    │                              │
    ┌───────────────▼───────────────┐              │
    │  ANALYZE (Engram)             │              │
    │  Outcome: success or burn?    │              │
    │  Detect: error cascades,      │              │
    │  danger zones, stuck loops    │              │
    └───────────────┬───────────────┘              │
                    │                              │
    ┌───────────────▼───────────────┐              │
    │  IDENTIFY (New)               │              │
    │  Find decision fork points    │              │
    │  "At seq 50, agent chose to   │              │
    │   grep logs instead of        │              │
    │   reading the Lambda code"    │              │
    └───────────────┬───────────────┘              │
                    │                              │
    ┌───────────────▼───────────────┐              │
    │  SIMULATE (Replay Engine)     │              │
    │  Fork at decision point       │              │
    │  Try alternative path         │              │
    │  Run in isolated worktree     │              │
    └───────────────┬───────────────┘              │
                    │                              │
    ┌───────────────▼───────────────┐              │
    │  LEARN (New)                  │              │
    │  Compare outcomes             │              │
    │  Store: "on this codebase,    │              │
    │  when you see X, do Y"        │              │
    │  Inject into next session     │              │
    └───────────────┘───────────────┘              │
                    │                              │
                    └──────────────────────────────┘
                         (next session starts)
```

## The Christmas Eve Proof

Session `1e28bfa0` — Dec 24, 2025:
- 426 messages, 76 errors, 0 files written
- Agent chased a Bridge webhook failure for the entire session
- Error cascade at sequences 276-316: grepping 5 different log files, never finding root cause
- Eventually found `flow-processBridgeWebhook` Lambda — but couldn't fix it

**What the loop would do:**

1. **RECORD**: Already captured — 187 artifacts in the session
2. **ANALYZE**: Engram flags it: burn session (41% error rate, 0 writes)
3. **IDENTIFY**: Fork point at ~seq 270. Agent chose to grep logs. Alternative: read the Lambda source code directly.
4. **SIMULATE**: Replay from seq 270, inject alternative instruction: "Read the Lambda handler source, don't grep logs"
5. **LEARN**: Store experience: "On monra-app, when webhook processing fails, read the handler source code first. Log grepping failed 5 times in session 1e28bfa0."
6. **Next session**: When a similar webhook failure occurs, inject the learned strategy before the agent starts flailing.

## What's Connected Today vs What's Missing

| Component | Status | Location |
|-----------|--------|----------|
| Session JSONL capture | Working | ~/.claude/projects/ (native) |
| Artifact extraction | Working | engram/recall/artifact_extractor.py |
| Cross-session analytics | Working | engram/brief.py, engram/stats.py |
| Burn session detection | Working (query) | Demonstrated in this session |
| Danger zone detection | Working | engram/brief.py `_dangerous_files()` |
| Multi-agent dashboard | Working | openclaw/dashboard/ (:8789) |
| Event replay (visual) | Working | Dashboard replay mode |
| Taskboard | Working | openclaw/taskboard/ (:8788) |
| Gource export | Working | Dashboard /api/export/gource |
| **Fork point detection** | **Not built** | Needs: heuristic to identify decision moments |
| **Isolated worktree execution** | **Not built** | Needs: git worktree + sandboxed agent runner |
| **A/B outcome comparison** | **Not built** | Needs: run two paths, compare artifacts |
| **Experience storage** | **Not built** | Needs: structured lessons database |
| **Experience injection** | **Partial** | Engram brief injects some context, but not learned strategies |

## Enterprise Value (from market research)

The self-improving loop is the long-term vision. But the **immediate** sellable product
is the observability layer alone:

1. **Security** ($50-200K/yr) — sensitive file access detection
2. **Accountability** ($30-100K/yr) — session-to-commit forensic linking
3. **Compliance** ($50-150K/yr) — SOC2/EU AI Act audit trail
4. **Risk** ($20-50K/yr) — pre-merge blast radius assessment

The replay/learning loop is the **moat** — what makes this defensible long-term.
But observability is the **wedge** — what gets you in the door today.

## Competitive Landscape (Feb 2026)

| Layer | Crowdedness | Key Players | Our position |
|-------|------------|-------------|-------------|
| LLM conversation tracing | Very crowded | Braintrust $80M, Arize $62M, LangSmith $45M | Not competing here |
| AI governance/compliance | Moderate | Zenity, Credo AI, Arthur AI | Adjacent — our audit trail feeds their frameworks |
| Agent workflow observability | Nearly empty | AgentOps (small), InfiniteWatch ($4M, customer-facing agents) | Different focus — they monitor customer-facing AI, we monitor coding agents |
| Agent simulation/replay | LangGraph only | LangGraph time-travel (LangChain-locked) | We're framework-agnostic (Claude/Codex/Cursor) |
| Cloud agent sandboxes | Emerging | Proliferate (YC), Devin (cloud) | We're local-first — different philosophy |
| **Local coding agent audit trails** | **Empty** | **Nobody** | **This is us** |
| **Self-improving from local history** | **Empty** | **Devin does it cloud-side** | **This is the moat** |

## How to Resume

1. Read this file for the full vision
2. Read `docs/DIRECTION.md` for the "stop building, measure" decision
3. Read `docs/experiment-tracking.md` for system comparison metrics
4. Read `docs/linkedin-validation.md` for demand validation posts
5. Read `docs/research/replay-engine-market-validation.md` for replay research
6. Check taskboard at http://localhost:8788 for task status
7. Check dashboard at http://localhost:8789 for live agent activity

## Claude Web Analysis (saved Feb 23, 2026)

From an independent analysis session (Claude web, not this agent):

> **What Proliferate actually is:** Cloud harness. They provision isolated cloud sandboxes,
> connect your toolchain (Sentry, Linear, GitHub, Slack), and run agents reactively — a
> Sentry error fires, an agent investigates, opens a PR. The whole thing lives in their cloud.
> Currently in beta, managed hosting requires early access.
>
> **What you built that's different:** Proliferate runs agents in their cloud. OpenClaw runs
> agents on your machine, in your worktrees, against your actual local environment. That's not
> a limitation — for a lot of developers that's a feature. No cloud setup, no secrets management,
> no sending your codebase to someone else's infrastructure. Same file-over-app philosophy as Chad.
>
> **Is the worktree/sandbox idea overcrowded?** Proliferate is doing cloud sandboxes. Nobody is
> doing local worktree-based parallel agent execution with a live dashboard tracking what each
> one does. That's a gap. Git worktrees are native, zero infrastructure, and your codebase
> never leaves your machine.
>
> **The next logical step:** The idea you're circling — agents proposing features or developing
> in sandboxed worktrees based on what users are saying — is actually the next logical step from
> what you already have. OpenClaw already tracks what agents do across worktrees. The missing
> piece is the trigger layer: user feedback or tickets coming in, agent spins up in a worktree,
> proposes a solution, you review it.

## Brand Awareness Note

Web search for "OpenClaw" (Feb 23, 2026) returned "5 Best OpenClaw Alternatives" articles
from adopt.ai, eesel.ai, KDnuggets, clawtank.dev, and others — listing alternatives like
NanoBot, ZeroClaw, PicoClaw, Moltis, IronClaw. This means the project name already has
some visibility in the ecosystem. Need to investigate whether this is our project or a
name collision with another "OpenClaw."

## Key Decisions Still Open

1. **Open source or closed?** — OSS gets adoption, closed captures value
2. **CLI-first or SaaS-first?** — CLI is built, SaaS needs infra
3. **Solo developer tool or team tool?** — Solo works today, team needs auth/RBAC
4. **Observability-first or replay-first?** — Observability sells now, replay is the moat
5. **LinkedIn validation before building more?** — Yes, per DIRECTION.md
6. **Trigger layer** — Should OpenClaw react to Sentry/Linear/GitHub events to auto-spawn agents in worktrees?
