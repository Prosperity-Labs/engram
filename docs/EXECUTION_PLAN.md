# Engram — Daily Execution Plan
**Start date: February 2026 · Target: First real users in 4 weeks**

---

## State of Play

### What exists right now ✓
- Standalone repo at `~/Desktop/development/engram/` — 9 files, 1,134 lines
- `pip install engram && engram install` works
- Session Inspector (JSONL → DAG, web UI at :8090)
- Memory compression (SessionEnd hook, freeform summaries)
- Smart Orchestrator (3-tier routing)
- SQLite + FTS5 search
- **All of the above is Claude Code-only and hardcoded to its JSONL format**

### The change this plan makes
Every piece of Engram now sits on top of an `AgentAdapter` layer.
No part of Engram's core — compression, manifest, replay — knows which agent ran the session.
That makes Engram the only cross-agent memory and observability tool in the space.

### Agent hook/SDK landscape (researched)
| Agent | Hook mechanism | Session format | Status |
|---|---|---|---|
| **Claude Code** | `SessionEnd` hook in `settings.json` | JSONL at `~/.claude/` | ✓ Already built |
| **Cursor** | `hooks.json` — `afterFileEdit`, `stop`, `beforeShellExecution`. Sends JSON to stdin of any script | Cursor transcripts dir | ✓ Ready to wire |
| **Codex (OpenAI)** | `notify` config for `agent-turn-complete` + `--json` JSONL stream + `~/.codex/history.jsonl` | JSONL | ✓ Ready to wire |
| **Gemini / Google** | TBD — adapter pattern makes it straightforward to add | TBD | Phase 2 |

---

## The Architecture (build once, everything else follows)

```
Any agent session
       ↓
  AgentAdapter
  (normalizes to EngramSession)
       ↓
  EngramSession  ← single internal format
  {
    session_id, agent, start_time, end_time,
    turns: [{role, content, tool_calls, tool_results}],
    raw_events: [...]
  }
       ↓
  ┌────────────┬──────────────┬────────────┐
  │  Manifest  │ Compression  │  Inspector │
  │  Writer    │  Pipeline    │  / DAG     │
  └────────────┴──────────────┴────────────┘
```

The adapters are thin. `ClaudeCodeAdapter` reads JSONL. `CursorAdapter` reads hook events.
`CodexAdapter` reads `~/.codex/history.jsonl` or the `--json` stream.
Everything above that line is agent-agnostic forever.

---

## The Rule
**One outcome per day. When it's done, stop.**
Not "work on X" — a done/not done binary you check off each night.

---

## Week 1 — Architecture + Ship (Feb 20–26)

> Goal: Multi-agent architecture in place, repo public, Cursor + Claude Code + Codex working

**Day 1 (Thu Feb 20)**
Outcome: `AgentAdapter` base class + `ClaudeCodeAdapter` refactor
- Define `EngramSession` dataclass — the normalized format all adapters produce
- Refactor existing JSONL parser into `ClaudeCodeAdapter(AgentAdapter)`
- All downstream code (compression, inspector) reads `EngramSession`, not raw JSONL
- Done when: existing Claude Code sessions still work perfectly through the new layer

**Day 2 (Fri Feb 21)**
Outcome: `CursorAdapter` wired — Cursor sessions flow into Engram
- Wire Engram's hook script into Cursor's `~/.cursor/hooks.json` as a `stop` hook
- `afterFileEdit` hook feeds file paths directly to manifest as they happen (no inference needed)
- Done when: a Cursor session ends and `engram inspect-list` shows it alongside Claude Code sessions

**Day 3 (Sat Feb 22)**
Outcome: `CodexAdapter` wired — Codex sessions flow into Engram
- Parse `~/.codex/history.jsonl` on `agent-turn-complete` notify event
- Extract `command_execution` and `file_changes` event types for manifest
- Done when: a Codex session appears in Engram alongside Cursor and Claude Code sessions

**Day 4 (Sun Feb 23)**
Outcome: Structured Summarization — sections match ARCHITECTURE.md, iterative merging
- Replace freeform compression with 5 explicit sections:
  `## Session Intent | ## Decisions Made | ## Errors & Resolutions | ## Current State | ## Next Steps`
- LLM must populate each section explicitly — empty = explicitly empty, not forgotten
- First compression: generate from scratch. Subsequent: merge new span INTO existing structure (not regenerate)
- Done when: `engram compress` on any session produces all 5 sections with real specifics, not vague prose

**Day 5 (Mon Feb 24)**
Outcome: Artifact Manifest — file paths first, schema from ARCHITECTURE.md
- SQLite `artifacts` table: `session_id, agent, type, target, detail, sequence, timestamp`
- `type` values: `file_read | file_write | command | api_call | error | error_resolved`
- Cursor: `afterFileEdit` writes rows in real time as files change (no post-hoc inference)
- Claude Code: SessionEnd hook extracts all `Read`, `Edit`, `Write`, `Bash` tool_use blocks
- Codex: `agent-turn-complete` parses `command_execution` and `file_changes` events
- **File paths only for now** — commands and APIs expand in Week 2
- Done when: manifest rows exist in SQLite for sessions from all three agents with correct paths

**Day 6 (Tue Feb 25)**
Outcome: Manifest survives compression + injected on startup
- On `engram compress`: manifest injected verbatim at top, never summarized
- Done when: compress output shows manifest block (deterministic) then structured summary

**Day 7 (Wed Feb 26)**
Outcome: GitHub repo public + README live
- Headline: "Persistent memory and artifact tracking for Claude Code, Cursor, and Codex"
- One screenshot showing sessions from two different agents side by side in `engram inspect-list`
- Install: `pip install engram && engram install`
- Done when: repo is public and a stranger understands the value in 10 seconds

---

## Week 2 — First Users (Feb 27 – Mar 5)

> Goal: 5 real installs, PyPI published, posts in 3 separate communities

**Day 8 (Thu Feb 27)**
Outcome: 3 personal DMs sent — one Claude Code user, one Cursor user, one Codex user
- Personal message: "Built cross-agent memory for Claude Code + Cursor + Codex. Would you try it?"
- Different agents = different communities = 3x surface area from day one
- Done when: 3 DMs sent, follow-up noted for 48h later

**Day 9 (Fri Feb 28)**
Outcome: `engram manifest show` CLI command
- Pretty-prints manifest for current or specified session, shows which agent produced it
- Done when: command works cleanly with no docs needed

**Day 10 (Sat Mar 1)**
Outcome: Commands + API calls added to artifact manifest
- Expand `artifacts` table rows for `command` and `api_call` types (file tracking already done)
- Add tool output hash to each artifact row: enables replay cache (if hash matches, return cached)
- Done when: manifest shows FILES + COMMANDS + API CALLS sections for sessions from any agent

**Day 11 (Sun Mar 2)**
Outcome: PyPI publish — `pip install engram` works globally
- Version 0.1.0
- `engram install` auto-detects which agents are installed and wires each one automatically
- Done when: fresh machine, `pip install engram && engram install` wires all detected agents

**Day 12 (Mon Mar 3)**
Outcome: Posts in all three communities
- Claude Discord: focus on manifest + compression
- Cursor community: focus on `afterFileEdit` precision (Cursor's hook is the most accurate)
- OpenAI/Codex community: focus on session continuity
- Same tool, different angle for each audience
- Done when: all three posts live

**Day 13 (Tue Mar 4)**
Outcome: Onboard one real user from any community, watch them install
- Screen share or async recording, note every friction point
- Done when: they have it running, you have a friction list

**Day 14 (Wed Mar 5)**
Outcome: Fix top 3 frictions + X/Twitter post with multi-agent angle
- Caption: "AI agents have amnesia. Engram fixes it — Claude Code, Cursor, and Codex.
  Deterministic artifact tracking that survives compression."
- Done when: post live, frictions fixed

---

## Week 3 — 10 Real Users (Mar 6–12)

> Goal: 10 installs from people you didn't personally recruit, Replay scaffolding started

**Day 15 (Thu Mar 6)**
Outcome: HN Show HN post
- Title: "Show HN: Engram – cross-agent artifact tracking for Claude Code, Cursor, and Codex"
- Lead with Factory.ai benchmark — industry-validated problem, your solution
- Done when: submitted and live

**Day 16 (Fri Mar 7)**
Outcome: Respond to every comment and install report, same-day fixes
- Done when: no unanswered comment/DM older than 4 hours

**Day 17 (Sat Mar 8)**
Outcome: Buffer / fix install bugs from HN traffic
- Update README with answers to the 3 most-asked questions

**Day 18 (Sun Mar 9)**
Outcome: README benchmark section
- Factory.ai 2.45/5 artifact score vs Engram's deterministic tracking
- Before/after: agent session with and without manifest

**Day 19 (Mon Mar 10)**
Outcome: `ReplayEngine` scaffolding — agent-agnostic
- `fork(session_id, node_id)` → creates `ReplaySession` from any agent's `EngramSession`
- No execution yet — data model only
- Done when: `from engram.replay import ReplayEngine` imports cleanly

**Day 20 (Tue Mar 11)**
Outcome: Tool response mocking from manifest cache
- `run(mode="recorded_tools")` replays pre-fork tool calls using manifest hashes
- Works for any agent — Cursor file edits, Codex command executions, Claude Code tool calls
- Done when: forked session replays pre-fork path without hitting external APIs

**Day 21 (Wed Mar 12)**
Outcome: `engram replay` CLI working end-to-end on a real past session
- Done when: you can demo it on a real session from any agent where something went wrong

---

## Week 4 — Replay Polish + First Value Signal (Mar 13–19)

> Goal: Replay demoable, first paying conversations, landing page

**Day 22 (Thu Mar 13)**
Outcome: Diff view — old output vs new output side by side
- Done when: diff renders in terminal clearly enough to screenshot

**Day 23 (Fri Mar 14)**
Outcome: Replay demo video using a Cursor session
- Use Cursor specifically: `afterFileEdit` makes it the most precise, so the demo is cleanest
- Done when: 60-90 second screen recording exists showing fork → change → diff

**Day 24 (Sat Mar 15)**
Outcome: Post the replay demo
- "Tenderly for AI. Works for Claude Code, Cursor, Codex. Replay from any node.
  Zero tokens for the pre-fork path."
- Done when: post live on X + relevant Discords

**Day 25 (Sun Mar 16)**
Outcome: Buffer / respond to replay feedback

**Day 26 (Mon Mar 17)**
Outcome: First value conversations — 3 active users
- Question: "Would you pay $X/month for cloud session storage + manifest sync across machines?"
- Ask one Cursor user, one Claude Code user, one Codex user — cross-agent answer matters
- Done when: 3 conversations had, answers recorded

**Day 27 (Tue Mar 18)**
Outcome: Landing page
- Hero: "Your AI agents finally remember — across Claude Code, Cursor, and Codex"
- Demo GIF, install command, GitHub link
- Done when: URL resolves, loads in under 2 seconds

**Day 28 (Wed Mar 19)**
Outcome: v0.2.0 release
- Tag the release, changelog, GitHub post
- Done when: `pip install engram==0.2.0` works, changelog is live

---

## What Changed vs Previous Plan

| Previous | Updated |
|---|---|
| Claude Code only | Claude Code + Cursor + Codex from Day 1 |
| JSONL parser hardcoded to Claude Code | `AgentAdapter` abstraction on Days 1-3 |
| README: "for Claude Code" | README: "for Claude Code, Cursor, Codex" |
| One community (Claude Discord) | Three communities — 3x surface area |
| `engram install` wires one hook | Auto-detects and wires all installed agents |
| Replay is Claude Code-specific | Replay is agent-agnostic via `EngramSession` |

The extra 3 days of adapter work in Week 1 pays back immediately:
- Cursor's `afterFileEdit` hook is more precise than JSONL inference (real-time, not post-hoc)
- Three separate communities to post in vs one
- "Cross-agent" is a moat Anthropic, OpenAI, and Google individually cannot match each other on

---

## What to Ignore for Now
- Gemini/Google adapter — add after v0.1.0, same pattern as Cursor/Codex
- Fundraising — wait for 10 upset-if-gone users
- Batch Regression + Simulation — Phase 3
- Domain Knowledge Graph for Monra — future Engram extension (noted in ARCHITECTURE.md)
- Paid tier / cloud storage — wait for Day 26 value conversations
- Web UI — keep terminal-first until someone asks
- `engram-graph` optional extension (ChromaDB + Memgraph) — separate package, not in core

## Ship With the Repo on Day 7
- `ARCHITECTURE.md` — explains the two-layer design, benchmark targets, build order
- This is the document that earns trust with contributors and sophisticated early users
- Do not simplify it — developers who read it should feel like you've done the thinking

---

## Weekly Check-in (every Sunday)
1. How many installed it this week without being personally asked?
2. Did anyone come back without prompting?
3. What's the #1 thing that confused people?
4. Which agent are users coming from?
   *(tells you where to focus community presence next week)*

**The signal:** someone who would be upset if Engram disappeared tomorrow.
That's the real first milestone. Everything else is setup.

---

*Roadmap version: Feb 2026 · Engram v0.1.0 → v0.2.0*
*Agent support: Claude Code ✓ · Cursor ✓ · Codex ✓ · Gemini (Phase 2)*
