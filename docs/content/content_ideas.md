# Content Ideas — Engram / Loopwright

## 1. Live Claude Code Session Recording ⭐
**Format:** Screen recording, 5-10 minutes, unedited
**What to capture:**
- Left: Claude Code terminal session
- Right: OpenClaw dashboard live (three lanes, events flowing)

**The moment that makes it:**
1. Start Claude Code cold on a real task
2. Run natural language Engram search mid-session — "how did we configure hooks last time"
3. Engram MCP surfaces the prior session automatically
4. Agent uses it, doesn't rediscover from scratch
5. Task completes — show the difference

**Accompanying post (one paragraph):**
"Watched my agent search its own memory mid-session and find something I built three weeks ago. Didn't have to explain it. Didn't have to paste context. It just knew. Here's the recording."

**When to record:** After Engram MCP + natural language search is working
**Platform:** LinkedIn, X, YouTube

---

## 2. The Experiment Post
**Format:** Static graphic + short post
**The graphic:** Split two-column comparison
- Left: Session A (cold). 17.2 min, 53% exploration, found target at tool call #8
- Right: Session B (with Engram). 7.6 min, 25% exploration, found target at tool call #5
- Center: **55% faster**
- Below: "The agent already knew where to look. Because it remembered what it did last time."

**When to post:** Now — this is ready today
**Platform:** LinkedIn, X

---

## 3. The Christmas Eve Case Study
**Format:** Written post / article
**The story:**
- Dec 24, 2025. Agent burns 426 messages, hits 76 errors, produces zero output
- Nobody knew until it was over
- What Engram sees: error cascade starting at message 50, pattern recognizable
- What Loopwright would have done: flagged at message ~50, spawned correction agent
- Cost saved: ~376 messages of wasted agent time

**The hook:** "You wouldn't know your agent was stuck until it was too late. Now you would."
**When to post:** After Loopwright correction loop is running
**Platform:** LinkedIn, dev.to, HackerNews

---

## 4. The Headless Agent Case Study
**Format:** Short post, 2 paragraphs
**The story:**
- Claude Code didn't know the established pattern for running headless agents via SDK
- Ran `engram search "headless"` — surfaced the prior session where we figured it out
- Agent used it immediately, problem solved in seconds not rediscovered from scratch

**The hook:** "The agent didn't know. Engram did."
**When to post:** Ready now — happened tonight
**Platform:** LinkedIn, X

---

## 5. The Loopwright Vision Post
**Format:** Architecture diagram + written vision
**The story:** Agents that write, test, self-correct, and ship. The full loop.
**Include:** Worktree → test → checkpoint → correct → staging → merge diagram
**When to post:** After first real correction cycle runs on monra-app
**Platform:** LinkedIn, HackerNews, dev.to

---

## 6. "What my agents built this week" recurring post
**Format:** Weekly, generated from Engram data
**Content:** Real stats from real sessions — files touched, sessions that shipped, sessions that burned, co-change patterns discovered
**The hook:** Sungman's model — people pay for the report. This is the free version that builds audience.
**When to start:** After first external user installs Engram
**Platform:** LinkedIn

---

## 7. "Same data, different questions" competitive landscape post
**Format:** Diagram + explanation
**The point:** Chad asks "what did we say?" Sungman asks "who built what?" You ask "what did the agent do and what broke?"
**Same JSONL files. Three different products. Three different buyers.**
**When to post:** After Chad tries Engram
**Platform:** LinkedIn, X

---

## Priority Order
1. **Post #2 (experiment)** — ready now, ship this week
2. **Post #4 (headless agent)** — ready now, ship this week
3. **Recording #1** — after MCP natural language search works
4. **Post #3 (Christmas Eve)** — after Loopwright correction loop runs
5. **Post #5 (vision)** — after first real correction cycle
6. **Post #6 (weekly)** — after first external user
7. **Post #7 (competitive)** — after Chad tries it

---

*Last updated: February 2026*
*Add ideas below as they come up*
