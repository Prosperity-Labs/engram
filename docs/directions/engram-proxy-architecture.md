# ENGRAM — The Nervous System for AI Agents

## The Thesis

Every AI agent operating today is blind, amnesiac, and alone.

Blind — it cannot see what it's doing to the codebase in context of what every previous agent has done. It edits a file without knowing that file has caused 7 failures in the last 3 sessions.

Amnesiac — it starts every session from zero. Monday's hard-won understanding of the webhook architecture is gone by Tuesday. The agent re-reads, re-explores, re-discovers — burning tokens and time on knowledge that existed yesterday.

Alone — when three agents work on the same codebase (Claude Code on backend, Cursor on frontend, Codex on tests), none of them know what the others are doing. They duplicate work, create conflicts, and make contradictory decisions.

Engram fixes all three. Not by making the agent smarter — by giving it a nervous system.

---

## The Biological Metaphor

A nervous system does not think. The brain thinks. The nervous system does three things:

1. **Senses** — it detects what's happening in real time
2. **Transmits** — it carries signals between the brain and the body
3. **Reflexes** — it triggers automatic responses to known patterns without waiting for the brain

Engram is the nervous system. The AI agent is the brain. The codebase is the body.

```
THE AGENT (Brain)
    Thinks. Plans. Reasons. Creates.
    │
    │ Every action passes through
    ▼
ENGRAM (Nervous System)
    Senses what's happening.
    Checks against accumulated knowledge.
    Fires reflexes for known patterns.
    Records everything for future learning.
    │
    │ Approved/augmented action
    ▼
THE CODEBASE (Body)
    Files. Tests. APIs. Infrastructure.
```

The brain doesn't need to know about the nervous system. It just acts, and the nervous system ensures those actions are informed by everything that came before.

---

## Architecture — Three Layers

### Layer 1: The Sensory Layer (Observation)

Every tool call the agent makes is an observable event. Engram intercepts and categorizes each one:

```
SENSORY EVENTS:

  FILE_READ    → Agent is exploring / gathering information
  FILE_EDIT    → Agent is modifying state (high-value event)
  FILE_WRITE   → Agent is creating new state
  BASH_EXEC    → Agent is interacting with the environment
  BASH_FAIL    → Agent hit an error (critical signal)
  GIT_OP       → Agent is managing version control
  GREP/GLOB    → Agent is searching (may indicate being lost)
  API_CALL     → Agent is interacting with external services
  SUBAGENT     → Agent spawned a child (parallel execution)
```

The sensory layer does not interpret. It classifies and forwards.

Latency budget: < 1ms per event. This is a classifier, not an analyzer.

### Layer 2: The Integration Layer (Knowledge)

Every sensory event is evaluated against Engram's accumulated knowledge. This is where observation becomes understanding.

```
KNOWLEDGE STRUCTURES:

  ┌─────────────────────────────────────────────────┐
  │           SPATIAL KNOWLEDGE                      │
  │  "The geography of the codebase"                │
  │                                                  │
  │  File Hotspots:                                  │
  │    handlers.ts → 182 reads, 79 writes, 22 sess  │
  │    alchemy-webhook.ts → 41 reads, 30 writes     │
  │                                                  │
  │  Co-Change Graph:                                │
  │    validators.ts ←→ endpoints.ts    (6x)         │
  │    handlers.ts   ←→ schemas.ts      (5x)         │
  │    schemas.ts    ←→ types.ts        (5x)         │
  │                                                  │
  │  Coupling Clusters:                              │
  │    [validators, endpoints, handlers,             │
  │     schemas, types, transfers]                   │
  │    = "the API layer" — touch one, check all      │
  └─────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────┐
  │           TEMPORAL KNOWLEDGE                     │
  │  "The history of what happened"                 │
  │                                                  │
  │  Session Trails:                                 │
  │    418 sessions, 20,700 tool calls               │
  │    Avg exploration ratio: 3.15:1                 │
  │    Avg session cost: $3.40 (median $0.82)        │
  │                                                  │
  │  Error Archaeology:                              │
  │    aws.ts: 7:1 error:write — IAM permissions     │
  │    session_db.py: 4:1 error:write — SQLite locks │
  │    ShareClaimSuccess.tsx: 11:3 — state mgmt      │
  │                                                  │
  │  Approach Memory:                                │
  │    "Mocking Alchemy webhook failed 3x.           │
  │     Real testnet worked on attempt 4."           │
  └─────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────┐
  │           STRATEGIC KNOWLEDGE                    │
  │  "What works and what doesn't"                  │
  │                                                  │
  │  Strategy Fitness:                               │
  │    "read_tests_first" → 0.82 fitness (bug_fix)   │
  │    "grep_for_error"   → 0.71 fitness (debug)     │
  │    "check_git_log"    → 0.65 fitness (refactor)  │
  │                                                  │
  │  Agent Profiles:                                 │
  │    Claude Code: best at refactoring (0.78)       │
  │    Cursor: best at UI work (0.81)                │
  │    Codex: best at test generation (0.74)         │
  │                                                  │
  │  Cost Models:                                    │
  │    bug_fix: median $2.10, P90 $15               │
  │    feature: median $8.40, P90 $45               │
  │    refactor: median $5.20, P90 $28               │
  └─────────────────────────────────────────────────┘
```

The integration layer answers one question: "Given what I know about the entire history of this codebase, is this tool call normal, risky, or wrong?"

Latency budget: < 10ms per lookup. Pre-loaded in memory at session start.

### Layer 3: The Reflex Layer (Intervention)

Reflexes are automatic responses to known patterns. They fire without asking the brain (agent). They are deterministic, testable, and falsifiable.

```
REFLEX TAXONOMY:

  OBSERVE (98% of events)
  ──────────────────────
  Default. Record the event. No intervention.
  The agent never knows Engram is there.
  Latency added: 0ms (async recording)


  AUGMENT (1-2% of events) 
  ────────────────────────
  Add information the agent doesn't have.
  
  Trigger: Agent edits validators.ts
  Reflex:  "Co-change alert: validators.ts has been 
           edited with endpoints.ts in 6/6 past sessions.
           Also check: schemas.ts (5x), handlers.ts (5x)"
  
  Trigger: Agent starts session on monra-core
  Reflex:  "Project context: 34 sessions, 4,783 msgs.
           Hot files: handlers.ts (182 reads).
           Active danger zone: aws.ts (7:1 error ratio)"
  
  Mechanism: Inject text into agent's context window
  Latency: < 5ms


  WARN (< 0.5% of events)
  ───────────────────────
  Flag a known danger pattern.
  
  Trigger: Agent edits aws.ts
  Reflex:  "⚠ DANGER ZONE: aws.ts has 7:1 error:write 
           ratio across past sessions. Common failure: 
           IAM permissions. Recommended: read test file 
           first, verify permissions before editing."
  
  Trigger: Agent bash command matches past failure
  Reflex:  "⚠ This command pattern failed 3x in past 
           sessions. The working approach was: [X]"
  
  Trigger: Exploration ratio exceeds 10:1
  Reflex:  "⚠ High exploration detected. 15 reads, 
           0 edits. Most likely targets based on 
           history: [file1, file2, file3]"
  
  Mechanism: Inject warning into agent's context
  Latency: < 5ms


  REDIRECT (< 0.1% of events)
  ──────────────────────────
  Suggest a fundamentally different approach.
  
  Trigger: Agent is on 3rd retry of failed approach
  Reflex:  "↻ This approach has been tried 3x in this 
           session. Past sessions resolved similar issues 
           by: [alternative approach]. Consider switching."
  
  Trigger: Agent token burn exceeds P90 with no commits
  Reflex:  "↻ This session has consumed $X with no 
           commits. Similar sessions that succeeded 
           pivoted to [approach] at this point."
  
  Mechanism: Inject suggestion into agent's context
  Latency: < 10ms


  BLOCK (< 0.01% of events)
  ────────────────────────
  Prevent known destructive actions. Deterministic.
  
  Trigger: rm -rf on production path
  Reflex:  "✋ BLOCKED. Destructive action on production 
           path. Requires human approval."
  
  Trigger: git push --force on main
  Reflex:  "✋ BLOCKED. Force push to main. 
           Requires human approval."
  
  Trigger: Agent about to exceed cost budget
  Reflex:  "✋ BLOCKED. Session cost would exceed 
           $50 budget. Requires human approval."
  
  Mechanism: Prevent tool execution, return denial
  Latency: < 1ms (must be instant)
```

---

## The Proxy — How It Physically Works

Four possible implementations, from simplest to most powerful:

### Implementation A: CLAUDE.md Rules (Works Today)

Engram analyzes its database and generates project-specific rules that get written to CLAUDE.md. The agent reads these at session start.

```
# Auto-generated by Engram — do not edit manually
# Updated: 2026-03-05 from 34 sessions on monra-core

## File Relationships (always edit together)
- validators.ts → also check endpoints.ts, schemas.ts
- handlers.ts → also check schemas.ts, transfers.ts  
- schemas.ts → also check types.ts

## Danger Zones (high error history)
- aws.ts: 7:1 error ratio — read tests before editing
- session_db.py: concurrent write issues — use WAL mode

## Known Failures (don't repeat these)
- Mocking Alchemy webhook: fails due to signature validation
  Working approach: use real testnet with test API key
- SQLite FTS on concurrent writes: use WAL + busy_timeout

## Project Stats
- 34 sessions, 4,783 messages, median cost $3.40
- Most edited: handlers.ts (79x), drops/[id]/page.tsx (51x)
```

Pros: Works immediately. Zero infrastructure.
Cons: Static. Only fires at session start. No mid-session intervention.

### Implementation B: Smart MCP Server (Works This Month)

Engram's MCP server becomes proactive. Instead of waiting for the agent to call `engram_recall`, it provides tools that the agent is instructed to call at key moments.

```
MCP Tools:
  
  engram_before_edit(file_path) → Returns co-changes + warnings
  engram_before_bash(command)   → Returns past failures for this pattern  
  engram_check_progress()       → Returns exploration ratio + suggestions
  engram_session_cost()         → Returns current cost estimate

CLAUDE.md instruction:
  "Before editing any file, call engram_before_edit with the file path.
   Before running unfamiliar bash commands, call engram_before_bash.
   Every 20 tool calls, call engram_check_progress."
```

Pros: Mid-session intervention. Uses existing MCP infrastructure.
Cons: Agent-initiated — the agent must choose to call the tools. Can be ignored.

### Implementation C: MCP Tool Shadowing (Works If Possible)

Register MCP tools that shadow Claude Code's built-in tools. When the agent calls "edit file", it actually calls Engram's version which checks, then delegates to the real tool.

```
MCP Tool Registration:
  
  engram_edit(file, old, new) → 
    1. Check co-changes, danger zones
    2. If safe: delegate to real Edit tool
    3. If risky: inject warning, then delegate
    4. If blocked: return denial
    
  engram_bash(command) →
    1. Check against failure history
    2. Check destructive patterns
    3. If safe: delegate to real Bash tool
    4. If known failure: inject alternative, then delegate
    5. If destructive: return denial
```

Pros: Transparent to agent. True proxy layer. Every action passes through.
Cons: May not be possible with current MCP spec. Requires investigation.

### Implementation D: Process Wrapper (The Full Tenderly)

Engram wraps the Claude Code process itself. All communication between the LLM and the tool execution layer passes through Engram.

```
Normal:     LLM  ←→  Claude Code Runtime  ←→  Tools
With Engram: LLM  ←→  Claude Code Runtime  ←→  ENGRAM PROXY  ←→  Tools

The proxy:
  1. Intercepts every tool call from the runtime
  2. Evaluates against knowledge engine
  3. Optionally augments, warns, redirects, or blocks
  4. Forwards to actual tool execution
  5. Captures result
  6. Returns to runtime (possibly with injected context)
```

Pros: Complete control. True Tenderly model. Agent-agnostic.
Cons: Requires deep integration with Claude Code internals. Most complex.

---

## Simulation: A Real Debugging Session With Engram Proxy

Let's simulate the Monra signup fix with Engram's proxy layer active.

```
SESSION START — monra-core
━━━━━━━━━━━━━━━━━━━━━━━━━━

Agent receives task: "The signup flow is broken — user_type 
and business_name aren't being passed through createUser"

┌─ ENGRAM REFLEX: SESSION_START (AUGMENT) ──────────────┐
│ Project: monra-core (34 sessions, 4,783 messages)      │
│ Relevant history: signup flow touched in 3 sessions    │
│ Hot files: handlers.ts (182 reads), validators.ts      │
│ Co-change cluster: [validators, endpoints, handlers,   │
│   schemas, types] — edit one, check all                │
│ Previous approach: user_type feature was built on      │
│   feat/user-type branch (Feb 25), unmerged             │
│ Danger: aws.ts has 7:1 error ratio                     │
└────────────────────────────────────────────────────────┘

  0:00  Agent: READ validators.ts
        ← Engram: OBSERVE (record, no intervention)

  0:15  Agent: READ createUser.ts
        ← Engram: OBSERVE

  0:30  Agent: READ handlers.ts
        ← Engram: OBSERVE

  0:45  Agent: EDIT validators.ts (+6 lines, user_type validation)
        ┌─ ENGRAM REFLEX: CO_CHANGE (AUGMENT) ──────────┐
        │ validators.ts was edited with these files in   │
        │ 6/6 past sessions:                             │
        │   → endpoints.ts (6x)                          │
        │   → handlers.ts (5x)                           │
        │   → schemas.ts (5x)                            │
        │   → types.ts (5x — via schemas.ts)             │
        │ Recommend: check all 4 after this edit.        │
        └────────────────────────────────────────────────┘
        Agent now knows to edit all 5 files, not just 1.

  1:00  Agent: EDIT createUser.ts (+2 lines)
        ← Engram: OBSERVE (createUser.ts not in co-change cluster — new signal recorded)

  1:15  Agent: EDIT schemas.ts (+6 lines)
        ← Engram: OBSERVE (expected from co-change alert)

  1:30  Agent: EDIT types.ts (+2 lines)
        ← Engram: OBSERVE (expected)

  1:45  Agent: BASH npm test
        ← Engram: OBSERVE → exit 0 → record success

  2:00  Agent: BASH cdk deploy
        ← Engram: OBSERVE → exit 0 → record success

  2:30  Agent: BASH curl -X POST /api/signup ...
        ← Engram: OBSERVE → exit 0 → record success

SESSION END — 2:30 total
━━━━━━━━━━━━━━━━━━━━━━━━

┌─ ENGRAM SESSION SUMMARY ──────────────────────────────┐
│ Duration: 2m 30s                                       │
│ Cost: $0.42                                            │
│ Tool calls: 10 (3 read, 4 edit, 3 bash)               │
│ Exploration ratio: 0.75:1 (excellent)                  │
│ Errors: 0                                              │
│ Interventions: 1 (co-change augment at 0:45)           │
│ Outcome: SUCCESS (tests pass, deployed, verified)      │
│                                                        │
│ Co-change alert impact: Agent edited all 4 related     │
│ files without additional exploration. Estimated         │
│ savings: 5-10 minutes of discovery + potential missed   │
│ file (endpoints.ts often forgotten).                    │
│                                                        │
│ Strategy recorded:                                     │
│   task_type: bug_fix                                   │
│   approach: direct_edit_with_cochange_guidance          │
│   fitness: 0.95                                        │
│   tokens: low                                          │
│   files: validators, createUser, schemas, types        │
└────────────────────────────────────────────────────────┘
```

---

## Simulation: What Happens WITHOUT the Proxy

Same task, same agent, no Engram:

```
SESSION START — monra-core (no Engram)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  0:00  Agent: GREP "createUser" → finds 8 files
  0:30  Agent: READ createUser.ts
  1:00  Agent: READ handlers.ts
  1:30  Agent: GREP "user_type" → finds 0 results (not implemented yet)
  2:00  Agent: READ schemas.ts
  2:30  Agent: READ types.ts
  3:00  Agent: GLOB "*.ts" in src/ → 47 files
  3:30  Agent: READ validators.ts
  4:00  Agent: READ endpoints.ts
  4:30  Agent: READ 3 more files looking for where user_type should go
  6:00  Agent: Finally understands the flow
        
  6:00  Agent: EDIT validators.ts (+6 lines)
  6:30  Agent: EDIT createUser.ts (+2 lines)
  7:00  Agent: EDIT schemas.ts (+6 lines)
  7:30  Agent: BASH npm test → FAIL (types.ts not updated)
  8:00  Agent: READ types.ts again
  8:30  Agent: EDIT types.ts (+2 lines)
  9:00  Agent: BASH npm test → PASS
  9:30  Agent: BASH cdk deploy
  10:00 Agent: Does NOT check endpoints.ts (forgotten)
        
  ...later, endpoints.ts causes a runtime error...
  
  12:00 Agent: DEBUG endpoints.ts error
  14:00 Agent: EDIT endpoints.ts
  15:00 Agent: BASH npm test → PASS
  15:00 Agent: BASH cdk deploy

SESSION END — 15:00 total
━━━━━━━━━━━━━━━━━━━━━━━━

  Duration: 15 minutes (6x longer)
  Tool calls: 25+ (2.5x more)
  Errors: 1 (missed endpoints.ts)
  The forgotten file caused a production issue
  The agent re-read types.ts because it forgot to edit it
```

---

## The Compound Effect

Session 1: Engram has no knowledge. It observes silently. No interventions.

Session 10: Engram knows the file hotspots. It can augment session starts with project context.

Session 50: Engram knows the co-change patterns. It fires co-change alerts on edits. It knows the danger zones.

Session 100: Engram knows which strategies work for which task types. It suggests approaches. It warns about known failures.

Session 500: Engram has a complete behavioral model of the codebase. It predicts which files will need editing from the task description alone. It routes tasks to the best agent (Claude Code for refactoring, Cursor for UI).

Session 5,000 (multi-team): Engram has learned patterns across codebases. A new team installs Engram and immediately benefits from aggregate knowledge: "TypeScript API layers typically have this co-change structure."

```
VALUE OVER TIME:

  Knowledge │                                    ╱
            │                                 ╱
            │                              ╱
            │                          ╱
            │                      ╱
            │                  ╱
            │             ╱
            │         ╱
            │      ╱
            │   ╱
            │╱
            └──────────────────────────────────────
              1    10    50   100   500  5000
                        Sessions

  The nervous system gets smarter with every session.
  The agent doesn't need to change.
  The codebase doesn't need to change.
  Only Engram's knowledge grows.
```

---

## Cross-Agent Nervous System

The ultimate vision: Engram is the shared nervous system across ALL agents working on a codebase.

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Claude Code   │  │   Cursor     │  │    Codex     │
│ (Backend)     │  │  (Frontend)  │  │   (Tests)    │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │
       └────────────┬────┴────────┬────────┘
                    │             │
              ┌─────▼─────────────▼─────┐
              │     ENGRAM PROXY         │
              │                          │
              │  One nervous system.     │
              │  Three agents.           │
              │  Shared knowledge.       │
              │                          │
              │  Claude edits handlers → │
              │  Cursor knows about it   │
              │  before its next session │
              │                          │
              │  Codex writes tests →    │
              │  Claude's next session   │
              │  knows what's tested     │
              │                          │
              │  Cursor touches page →   │
              │  Engram alerts: "Claude  │
              │  is also working on the  │
              │  API that feeds this     │
              │  component right now"    │
              └─────────────────────────┘
```

No agent has this today. Not GRIP (single agent). Not Tastematter (context graph, not cross-agent). Not Anthropic (Claude Code only). Not Codified Context (single system).

This is the Tenderly/Insightful/Datadog play:
- **Tenderly** made blockchain transactions visible across all contracts
- **Insightful** made human work visible across all employees  
- **Datadog** made infrastructure visible across all services
- **Engram** makes AI agent behavior visible across all agents

---

## The Intervention Budget

A nervous system that fires constantly is noise. A nervous system that never fires is dead.

The rule: **2-3 meaningful interventions per session. No more.**

```
INTERVENTION BUDGET:

  Session start:     1 augment (project context)
  During session:    1-2 augments/warns (co-change, danger zone)  
  Session end:       1 summary (cost, outcome, strategy recorded)
  
  Blocks:            Only for genuinely destructive actions
  Redirects:         Only after 3+ failed attempts at same approach

  Total agent disruption per session: < 5 seconds of reading injected context
  Total value per session: prevented errors, faster convergence, no forgotten files
```

The intervention budget is the difference between a helpful nervous system and an annoying linter. Less is more. Every intervention must carry information the agent cannot obtain from reading code.

---

## What Engram Knows That Code Doesn't

This is the fundamental insight. Code is a snapshot. Engram is the history.

```
CODE TELLS YOU:              ENGRAM TELLS YOU:
─────────────────            ──────────────────
What the function does       How many times agents misunderstood it
What the types are           Which types are always forgotten
What the tests cover         Which tests fail most often
What the API shape is        Which endpoints are always edited together
What the config says         Which config changes broke production
What the README says         Whether agents actually follow the README
```

An agent reading code sees the present. An agent with Engram sees the present informed by everything that ever happened.

---

## Implementation Phases

### Phase 0: CLAUDE.md Generator (This Week)
Engram generates project-specific rules from its data.
Static injection at session start. Zero infrastructure.
Validates whether the knowledge is useful at all.

### Phase 1: Smart MCP Tools (This Month)
engram_before_edit, engram_before_bash, engram_check_progress.
Agent-initiated but instructed to call at key moments.
Mid-session intervention becomes possible.

### Phase 2: MCP Tool Shadowing (Month 2)
Investigate whether MCP tools can shadow built-in tools.
If yes: transparent proxy layer, agent doesn't know Engram exists.
If no: fall back to Phase 1 with stronger CLAUDE.md instructions.

### Phase 3: Process Wrapper (Month 3-4)
Full Tenderly model. Engram wraps the agent process.
Complete control over every tool call.
Agent-agnostic: works with Claude Code, Cursor, Codex.

### Phase 4: Cross-Agent Nervous System (Month 4-6)
Multiple agents connected to same Engram instance.
Real-time awareness across agents.
Conflict detection, work deduplication, shared learning.

### Phase 5: Team Layer (Month 6-8)
Multiple developers' Engram instances sharing anonymized knowledge.
Team dashboard showing all agent activity.
Cost analytics, waste detection, strategy benchmarking across team.

---

## The North Star

A developer installs Engram. They run their AI agents as usual.

Over days, Engram silently learns their codebase — which files matter, which patterns work, which mistakes repeat, which approaches succeed.

Over weeks, Engram starts intervening — catching forgotten files, warning about danger zones, preventing repeated failures. The developer's agents get measurably better without the developer doing anything.

Over months, Engram becomes the institutional memory of the codebase — a nervous system that every agent, current and future, benefits from. New team members' agents immediately work as if they've been on the project for months.

The agent is the brain. Engram is the nervous system. Together, they don't just code — they learn.

---

*Built by Prosperity Labs*
*The nervous system for AI agents.*
