# Engram 4-Week Sprint

## WEEK 1 — Foundation
- **Day 1 (Today):** AgentAdapter base class, refactor JSONL parser into ClaudeCodeAdapter. Fix engram PATH so it runs from anywhere.
- **Day 2:** CursorAdapter — wire Cursor stop hook, sessions appear in engram inspect-list
- **Day 3:** CodexAdapter — wire Codex notify hook, same
- **Day 4:** Structured summarization — 5 sections: Intent, Decisions, Errors, Current State, Next Steps
- **Day 5:** Artifact Manifest — SQLite artifacts table, file paths from all three agents
- **Day 6:** Manifest survives compression, injected on SessionStart automatically (fix the "agent skipped recall" problem)
- **Day 7:** GitHub README live — "Cross-agent memory for Claude Code, Cursor, Codex." Ship it.

## WEEK 2 — First Users
- **Day 8:** 3 personal DMs — one per agent community
- **Day 9:** engram manifest show CLI command
- **Day 10:** Commands + API calls added to manifest, tool output hashing
- **Day 11:** PyPI publish — pip install engram works globally
- **Day 12:** Posts in Claude Discord, Cursor community, Codex community
- **Day 13:** Watch one real user install, note every friction
- **Day 14:** Fix top 3 frictions, post on Twitter with multi-agent angle

## WEEK 3 — 10 Users
- **Day 15:** HN Show HN — lead with Factory.ai 2.45/5 benchmark
- **Day 16:** Respond to everything same-day
- **Day 17:** Fix install bugs, update README
- **Day 18:** Add benchmark section to README — Factory.ai vs Engram
- **Day 19:** ReplayEngine scaffolding — agent-agnostic data model
- **Day 20:** Tool response mocking from manifest cache
- **Day 21:** engram replay CLI working end-to-end

## WEEK 4 — Replay + First Signal
- **Day 22:** Diff view for replay
- **Day 23:** Replay demo video using Cursor session
- **Day 24:** Post replay demo — "Tenderly for AI"
- **Day 25:** Buffer / feedback
- **Day 26:** 3 value conversations — "Would you pay for cloud sync?"
- **Day 27:** Landing page — one HTML file
- **Day 28:** v0.2.0 release, changelog
