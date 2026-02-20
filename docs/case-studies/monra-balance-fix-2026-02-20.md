# Engram Case Study — February 20, 2026

## Engram Found What the Plan Missed

**Project:** Monra — fintech payment infrastructure
**Task:** Balance & Transaction Correctness Fix (5 tasks, 4 files)
**Session length:** ~4 hours
**Key finding:** 30-45 minutes saved on unplanned work

---

## Background

We had a detailed, well-researched implementation plan for fixing stuck transactions, balance drift, and incorrect frontend classification across Monra's ledger system.

Claude Code went straight to implementation without querying Engram — exactly what any agent does today. No memory. No prior context. Start from scratch every session.

After the session ended, we ran three retroactive Engram searches to measure what would have been found if Engram had been queried at session start.

---

## The Retroactive Queries

```bash
engram search "balance fix attribution" --limit 3
# → 3 results found

engram search "transfer link handlers escrow" --limit 5
# → 5 results found

engram search "CDK stack Lambda linkTransferBroadcastSuccess deploy" --limit 3
# → 3 results found
```

---

## What Engram Found

### Query 1: "balance fix attribution"
**Most relevant:** Feb 7 session — balance correct but transaction amounts stale.
Mentions `attributeTransaction` needing `destinationAmount`.
Directly relevant to the balance/transaction interaction patterns in our fix.

### Query 2: "transfer link handlers escrow"
**Gold:** Feb 16-17 sessions contained the full dependency chain the plan missed:
- No webhook handler for escrow deposits
- Handlers use legacy balance check, no escrow_lock/escrow_release transactions
- The gap between `transfer_link_created` vs `escrow_lock` naming — plan confusion vs implementation reality
- `linkTransferBroadcastSuccess` end-to-end wiring listed as pending — exactly what we fixed

**This was the most valuable finding.** The Feb 16-17 sessions would have revealed the full CDK, API gateway, types, and schemas dependency chain that the plan didn't mention because the planner didn't know it existed.

### Query 3: "CDK stack Lambda deploy"
**Critical:** A CDK deletion incident — CloudFormation deleting live Lambdas — was documented in past sessions. No prior CDK deployment context existed in Engram before this session, confirming: if Engram had been running during the Feb 17 sessions when those Lambdas were first created, we would have known about the risk.

---

## The Numbers

| Scenario | Planned tasks (1-4) | Unplanned infrastructure |
|---|---|---|
| Without Engram | baseline | +30-45 min debugging |
| With Engram (retroactive) | ~10 min saved | **would have been prevented** |

**Net estimate: 30-45 minutes saved on a single session on unplanned work alone.**

The planned tasks themselves — mechanical `completeTransaction()` calls and a type map refactor — benefited minimally. The agent could read the files directly and the plan was specific enough.

---

## The Key Insight

> **Engram's highest value is surfacing implicit dependencies that aren't in the plan.**

The plan didn't mention CDK, API gateway, or the escrow_lock naming gap — because the planner didn't know they existed. Engram did. The past sessions had this knowledge. The agent just never asked.

This is the fundamental problem with AI agents today: every session starts from zero. Plans miss what the planner doesn't know. Engram closes that gap.

---

## The Fix This Proves

The agent skipped Engram voluntarily. The recall step was optional, so it was skipped.

**The solution:** SessionStart auto-injection. Before the agent makes its first tool call, Engram automatically queries past sessions based on current project context and injects the results. The agent can't skip what it never chose to do.

This is Day 6 of the execution plan.

---

## Industry Context

Factory.ai's research on agent memory shows that even best-in-class structured summarization approaches score **2.45/5** on artifact tracking — knowing which files were touched during a session. They explicitly call this out as requiring a separate artifact index.

Engram's deterministic manifest parsing (not LLM inference — actual tool call extraction from JSONL) achieves this with certainty, not probability. Every `Read`, `Edit`, `Write`, and `Bash` call is captured as a structured artifact row.

---

## The Claim, Proven

> "AI agents have amnesia. Engram fixes it — not with better summarization, but with a deterministic artifact trail and cross-session memory that survives compression."

One session. Real production codebase. Real time saved. Real finding: the CDK dependency chain that nearly caused a production incident, sitting in past sessions, waiting to be asked.

---

*Engram v0.1.0 — February 2026*
*github.com/[aleksa]/engram*
