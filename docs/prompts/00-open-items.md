# Engram Proxy & Enrichment — Open Items

## Bugs / Fixes
1. **Project resolution picks wrong match** — `_resolve_project()` in `engram/proxy/enrichment.py` finds `engram` (5 sessions) instead of the full path (25 sessions, 5,688 msgs). Should prefer match with most sessions.
2. **Key Decisions truncated mid-sentence** — snippets cut at 120 chars with no sentence boundary logic in `brief.py`
3. **Force push still needed** — `git push origin main --force-with-lease` to strip strategic docs from GitHub history

## Enrichment Quality (Prompt #01)
4. **Aggregate all project variants** — brief should combine data from all matching project names (short name, full path, worktrees, loopwright runs)
5. **Richer brief content** — recent activity, session stats, recurring errors with file context — not just file stats
6. **Brief quality scoring** — measure how many chars/sections each project gets, track improvement over time

## Proxy Data Collection (Prompt #02)
7. **Store request/response bodies** — needed for replay experiments, decision trace analysis, and deeper analytics
8. **Session detection in proxy** — group proxy_calls into logical sessions (same system prompt hash, time window)
9. **Automated session_metrics table** — turns-to-first-edit, exploration cost, error count per session

## A/B Experimentation (Prompt #03)
10. **Per-session coin flip** — randomize enrichment on/off per session for clean comparison
11. **Turns-to-first-edit metric** — automated scoring of exploration waste per session
12. **Paired experiment runner** — git worktrees + cold cache gap + comparison report
13. **Shadow replay engine** (future) — replay completed sessions with opposite variant

## Infrastructure
14. **DDD isolation for replay** — modularize agent knowledge vs execution so you can test enrichment on smaller scales without side effects
15. **`engram proxy dashboard`** — real-time analytics command showing enrichment effectiveness over time

## Execution Order
Prompt #01 (brief quality) → Prompt #02 (session metrics) → Prompt #03 (experiment runner)

Each builds on the previous. #01 makes enrichment worth testing, #02 gives you the metrics, #03 automates the testing.
