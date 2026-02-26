# Case Study: Session Archaeology — Tracing When and Why Code Was Built

> Date: 2026-02-22
> Query: "Where did the OpenClaw dashboard come from?"
> Time to answer: ~30 seconds (4 Engram queries)

## The Question

Two days after the OpenClaw dashboard was built, the developer couldn't remember
when it was created, what the intention was, or which session produced it. The dashboard
was running at http://localhost:8789 but its origin was unknown.

## What Engram Found

### Query 1: `engram search "openclaw dashboard"`
Found 10 results pointing to two sessions on **February 20, 2026**.

### Query 2: Session metadata lookup
```
Session 9ed41bb5  |  396 messages  |  Feb 20, 22:18 UTC  |  Planning + infrastructure
Session dce5828e  |  154 messages  |  Feb 20, 23:35 UTC  |  Dashboard build
```

### Query 3: Artifact extraction from both sessions

**Session 1 (planning)** — 21 file writes, mostly `run-multi.sh` (written 11 times):
- Developer asked: "Hey! What is the roadmap in this repository?"
- Then: "show me the build log and learnings"
- Then: "Cool. let's run the dashboard, and see if we configured all of this properly"
- This session set up the multi-agent pipeline infrastructure

**Session 2 (build)** — 15 file creates, the actual dashboard:
- Developer gave explicit plan: "Implement the following plan: OpenClaw Agent Visualization Dashboard"
- Agent created 11 files in 6 phases over ~20 minutes:
  1. `package.json`, `event-schema.js`, `event-store.js`, `server.js`
  2. `log-parser.js` (regex patterns for agent logs)
  3. `public/index.html` (1100+ lines, 3-lane UI, dark theme)
  4. Replay mode with transport controls
  5. `gource-exporter.js`, `excalidraw-exporter.js`
  6. Integration with `run-multi.sh`, taskboard poller, git watcher

### Query 4: User messages from both sessions
Extracted the developer's exact words, showing the progression from exploration
to spec to build.

## What This Demonstrates

### For developers (accountability)
- "Who built this and when?" — answered from session artifacts, not git blame
- Git shows *what* changed. Engram shows *why* — the user messages that led to each file

### For teams (forensics)
- When a feature is built across multiple sessions, Engram links them
- Session 1 (planning) naturally led to Session 2 (build) — 77 minutes apart
- The `run-multi.sh` file was written **11 times** in session 1 — a hotspot that
  signals iteration difficulty. Engram surfaces this automatically.

### For compliance (audit trail)
- Full provenance: developer intent → agent action → file created
- Every file creation timestamped with session context
- 306 events, 51 runs tracked across the dashboard's lifetime

## Enterprise Value

This is the **accountability** tier ($30-100K/yr):
- Session-to-code forensic linking
- "Which AI agent session produced this feature?"
- "What was the developer's intent when this was built?"
- No other tool answers these questions for local coding agent sessions

## Raw Data

```
Sessions:     9ed41bb5, dce5828e
Date:         February 20, 2026 (evening)
Total msgs:   550 (396 + 154)
Files created: 11 dashboard files
Time span:    ~2 hours (22:18 to 23:55 UTC)
Dashboard:    http://localhost:8789
Events:       306 captured, 51 runs detected
```
