# Engram Strategic Direction

## The One Sentence

The proxy is the product. Everything else is a feature of the proxy.

---

## Why the Proxy Wins

Every competitor is building tools the agent has to **choose** to use:

| Competitor | Approach | Fatal Flaw |
|---|---|---|
| GRIP | Specific commands | Agent must cooperate |
| Tastematter | Query interface | Agent must query |
| Open Brain | MCP calls | Agent must call |
| Rajan's claude-watch | Passive monitoring | Can't intervene |
| everything-claude-code | Hackathon winner, claims 50% token reduction | Unknown architecture |

**A proxy doesn't ask permission.** It sits between the agent and the world. Every API call passes through it. The agent doesn't know Engram exists — it just works better because Engram is enriching the context, catching mistakes, and injecting knowledge silently.

That's the Tenderly insight. Tenderly doesn't ask smart contracts to cooperate. It wraps the execution environment.

---

## Can We Actually Build It?

Yes. Two things prove it:

1. **Rajan's claude-watch** — uses mitmproxy to intercept HTTPS traffic between Claude Code and Anthropic's API. Sees every prompt and response. But he only watches — he doesn't modify.

2. **LiteLLM proxy** — people already redirect Claude Code through a proxy that swaps the model. Claude Code doesn't know the difference.

Engram combines both: **intercept like Rajan, modify like LiteLLM, add intelligence from Engram's knowledge.**

---

## The Architecture

```
Claude Code sends API request
         ↓
ENGRAM PROXY (localhost:9080)
         ↓
1. INSPECT the request
   - What files is the agent about to touch?
   - What tool calls is it making?
   - What's the current token count / cost?
         ↓
2. ENRICH the request (modify the prompt)
   - Append co-change warnings to system context
   - Inject danger zone alerts
   - Add strategy suggestions
   - Insert relevant knowledge graph subgraph
         ↓
3. FORWARD to Anthropic API (or any model)
         ↓
4. INSPECT the response
   - What did the model decide to do?
   - Did it ignore the warnings?
   - Record everything to Engram's database
         ↓
5. RETURN to Claude Code (possibly modified)
```

The key insight: you're modifying the **messages array** before it hits the API. The system prompt, the conversation history, the tool results — all pass through your proxy. You can append context to any message.

---

## What's Realistic Right Now (This Month)

Build a basic proxy that does three things:

**One — Logs everything.** Every request and response passes through, gets recorded in Engram's database. This alone is more valuable than Rajan's monitor because you're capturing at the API level with full message content, not just network traffic metadata.

**Two — Enriches system prompts.** On every request, the proxy checks which project the agent is working on, queries Engram's co-change patterns and danger zones, and appends a small context block to the system message. Maybe 200-500 tokens. The agent reads it automatically as part of its instructions.

**Three — Tracks cost in real time.** Every request/response pair has token counts. The proxy accumulates them and can block requests that would exceed a budget.

That's the MVP proxy. No knowledge graph needed yet, no evolutionary layer, no simulation. Just intercept, enrich with what you already have in SQLite, and forward.

---

## What's Visionary (3-6 Months)

The proxy becomes the **universal nervous system layer**. It works with any agent that makes API calls — Claude Code, Cursor, Codex, OpenCode, anything. You don't need agent-specific adapters anymore. If it calls an LLM API, Engram can wrap it.

The enrichment evolves from static co-change rules to **knowledge graph traversal**. The proxy queries Memgraph for the relevant subgraph and injects it. 200 tokens of structured relationships instead of the agent exploring for 20 minutes.

The proxy starts **blocking**, not just warning. The evolutionary layer scores which interventions actually helped and the proxy learns to intervene less but better over time.

**Multiple agents on the same project share the same proxy.** Claude Code edits a file, the proxy records it, and when Cursor starts a session 10 minutes later, the proxy enriches its context with "Claude Code just edited this file, here's what changed."

---

## The Technical Starting Point

```python
# engram/proxy/server.py
# A minimal HTTPS proxy that intercepts Anthropic API calls

from mitmproxy import http
import json

class EngramProxy:
    def request(self, flow: http.HTTPFlow):
        if "api.anthropic.com" in flow.request.host:
            body = json.loads(flow.request.content)
            project = detect_project(body)
            context = engram_context(project)
            if context:
                body["system"] = body.get("system", "") + context
                flow.request.content = json.dumps(body).encode()

    def response(self, flow: http.HTTPFlow):
        if "api.anthropic.com" in flow.request.host:
            engram_record(flow.request, flow.response)
```

That's maybe 100 lines to get the basic proxy working. The enrichment logic draws from the existing SQLite data. No new infrastructure needed for the MVP.

---

## The Build Sequence

```
Week 1: Basic mitmproxy interceptor that logs all Claude Code API calls
Week 2: Add co-change and danger zone injection into system prompts
Week 3: Add cost tracking and budget enforcement
Week 4: Test on your own Monra work for a full week — measure impact

Month 2: Add Memgraph, replace static rules with graph queries
Month 3: Multi-agent support (same proxy, multiple agents)
Month 4: Evolutionary scoring of interventions
```

---

## The Feature Hierarchy

Everything is a feature of the proxy:

```
                    ENGRAM PROXY
                    (the product)
                         │
          ┌──────────────┼──────────────┐
          │              │              │
    Knowledge       Algorithms      Evolution
    (SQLite +       (PageRank,      (Strategy
     Memgraph)      community,      fitness,
                    shortest path)  scoring)
          │              │              │
          └──────────────┼──────────────┘
                         │
                    Intelligence
                    that makes the
                    proxy smarter
```

Without the proxy, these are standalone tools — interesting but inert.
With the proxy, they become the nervous system.

---

## The Self-Funding Model Applied

From the task audit (440 sessions, $4,993 total spend):

| Lever | Current Cost | Proxy Saves | How |
|---|---|---|---|
| File re-reads (9,093 calls) | ~40% of token cost | 20-30% reduction | Inject project context, reduce exploration |
| Monra handler triad | $1,786 (36% of spend) | 15-20% reduction | Co-change alerts prevent forgotten files |
| Error-heavy sessions | $192+ per bad session | Prevent 50%+ | Danger zone warnings before edits |
| Memory agent copy-paste (20x) | Time waste | Eliminate | Auto-inject via proxy, not manual |

Conservative estimate: **20% cost reduction = ~$1,000/year saved** on a single developer's workflow.

At team scale (10 devs, $50K/year AI spend): **$10K/year savings** from proxy enrichment alone, before any advanced features.

---

## The Go-to-Market Question

**Who pays for this?**

Not individual developers (margin too thin at $1K/year savings).

The paying customer is **the engineering org spending $50K+/year on AI tokens** that wants:
1. Visibility into what agents are doing across the team
2. Cost control (budget enforcement per project/developer)
3. Knowledge sharing (one developer's debug session helps everyone)
4. Compliance (audit trail of every AI-generated code change)

The proxy gives you all four. The open-source repo gives you distribution. The hosted proxy gives you revenue.

---

*The proxy is the direction. Build it this week. Everything else follows.*
