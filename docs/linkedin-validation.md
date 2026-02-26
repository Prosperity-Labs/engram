# LinkedIn Demand Validation — Engram

## Post Option A: The "Oh Shit" Moment (Security angle)

---

I ran an audit on 290 AI coding agent sessions across my projects.

Here's what I found:

- Agents accessed .env files 25 times (and WROTE to them 23 times)
- Agents modified Dockerfiles, token files, and infra configs 110+ times
- One session burned 426 messages debugging a webhook failure — zero files fixed, zero humans notified
- One file (handlers.ts) was rewritten 75 times across 12 sessions by AI agents

Nobody flagged any of this. No alerts. No audit trail. Nothing.

We're giving AI agents access to our codebases and have zero visibility into what they actually do.

Every observability tool (Langfuse, Braintrust, Datadog) tracks what the LLM SAID.
Nobody tracks what the agent DID — which files it read, modified, deleted, what commands it ran.

With EU AI Act enforcement hitting August 2026 and SOC2 auditors starting to ask about AI coding tools — this gap is about to become a real problem.

I'm building an open-source tool that creates an audit trail for AI coding agents (Claude Code, Cursor, Codex). Think "Datadog for what AI agents do to your codebase."

Question for engineering leaders and CISOs:

Would you use a tool that shows you:
- Every file your AI agents touched (reads, writes, deletes)
- Which sessions were "burn sessions" (high cost, zero output)
- Sensitive file access alerts (.env, credentials, infra)
- Compliance-ready reports for auditors

Genuine question — trying to understand if this is a real pain point or just mine.

#AIAgents #DevTools #Engineering #Security #Compliance

---

## Post Option B: The Data Story (shorter, more viral)

---

I analyzed 52,000 messages from 290 AI coding agent sessions.

The scariest finding wasn't the errors or the cost.

It was this: AI agents accessed sensitive files (.env, tokens, credentials, Dockerfiles) 110 times across my projects.

Nobody was notified. No audit trail exists.

We have observability for our servers, our databases, our APIs.
We have zero observability for what AI agents do to our code.

Every tool in the market tracks the LLM conversation.
Nobody tracks the side effects — the files changed, commands run, secrets accessed.

I built a tool that extracts a deterministic audit trail from Claude Code / Cursor / Codex sessions. No AI summarization — pure action logging.

Thinking about open-sourcing it. Would this be useful to your team?

#AIAgents #DevOps #Security

---

## Post Option C: The Question Post (engagement optimized)

---

Quick poll for engineering teams using AI coding agents (Claude Code, Cursor, Copilot, Devin):

Can you answer these questions right now?

1. Which files did AI agents modify in your codebase this week?
2. Did any agent access .env files, credentials, or infra configs?
3. How many agent sessions produced zero useful output (burned tokens)?
4. If production breaks tomorrow — was it human code or agent code?

If you answered "no" to most of these — you're not alone.

I've been building an observability layer for AI coding agents. Not for the LLM conversation — for the actual actions. Files touched, commands run, errors hit, sensitive access.

Curious: which of these would matter most to your team?

A) Security alerts (agent touched sensitive files)
B) Accountability (link agent sessions to code changes)
C) Compliance reports (SOC2 / EU AI Act audit trail)
D) Cost control (detect stuck/wasteful agent sessions)

Drop a comment — genuinely trying to figure out where the pain is sharpest.

---

## Follow-up DM / One-Pager (send when people respond)

---

### Engram — AI Agent Observability

**The problem:** AI coding agents (Claude Code, Cursor, Copilot, Codex) modify your codebase with zero audit trail. When the SOC2 auditor asks "what did your AI tools change?" — nobody has an answer.

**What it does:**
- Extracts a deterministic audit trail from agent sessions (no AI summarization)
- Tracks every file read, write, create, command executed, and error
- Detects sensitive file access (.env, credentials, infra configs)
- Identifies "burn sessions" (high cost, zero output — agent stuck in loops)
- Cross-session intelligence: danger zone files, co-change patterns, hotspots
- Works with Claude Code, Cursor, and Codex today

**Real numbers from my usage:**
- 290 sessions analyzed, 16,303 actions extracted
- 110 sensitive file accesses detected (25 .env writes)
- 10 burn sessions identified (1000+ wasted messages)
- 8 hotspot files flagged for human review

**What I'm exploring:**
- Open source CLI (works today, pip install)
- Hosted dashboard with team visibility
- Compliance export (SOC2, EU AI Act)
- Tamper-evident audit chain (Merkle hash or blockchain anchoring)
- Pre-merge risk scores for agent-generated PRs

**I'd love to understand:**
1. Is this a problem your team faces today?
2. What would make this worth paying for?
3. Who would own this internally — security, engineering, compliance?

---

## Targeting Notes

**Who to reach out to:**
- VP Engineering / Head of Engineering at Series B+ startups (50-500 devs)
- CISOs at companies adopting AI coding tools
- DevOps / Platform engineering leads
- Compliance officers at fintech, healthtech, regulated industries
- Engineering managers who approve AI tool budgets

**Hashtags that work:**
#AIAgents #DevTools #Engineering #Security #SOC2 #Compliance #ClaudeCode #Cursor #CodingAgents #DevOps #CISO

**Best posting times (LinkedIn):**
- Tuesday-Thursday, 8-10 AM local time
- Engage with every comment within first 2 hours

**Follow-up strategy:**
- Anyone who comments "yes" or shares → DM with one-pager
- Anyone who asks questions → detailed response in comments (visibility)
- Track responses in a spreadsheet: name, company, role, pain point mentioned
