# Case Study: Headless Agent Spawning via Engram Search

**Date:** 2026-02-26
**Context:** Loopwright Sprint 1 — kicking off two parallel agents (Cursor + Codex) to build Phase 3 overnight

## Problem

We had agent prompts written and committed for two parallel builds:
- **Cursor Agent** → Engram repo (correction brief injection + query helpers)
- **Codex** → Loopwright repo (watchdog, spawner, test-runner, correction-writer)

We needed to launch both headlessly from the terminal. We knew the commands existed
from prior sessions but couldn't remember the exact CLI flags — especially for Cursor,
which has a separate `cursor-agent` binary with non-obvious flags.

The initial assumption was "Cursor doesn't have a headless CLI" based on the hook-based
capture system in `engram/hooks/cursor_hook.py`. This was wrong.

## How Engram Found It

### Search 1: Cursor headless CLI
```bash
engram search "cursor headless CLI run agent"
```
**Result:** Found 20 results across 4 sessions. The key hit was session `107fbbe6` (Feb 24):

> The user runs `cursor-agent` (the Cursor CLI) in headless mode:
> - CLI tool: `~/.local/bin/cursor-agent`
> - Headless execution: `cursor-agent -p "prompt"`
> - Output format: `--print --output-format json` or `--output-format stream-json`
> - Workspace: `--workspace <path>`

### Search 2: Codex headless flags
```bash
engram search "codex exec headless spawn"
```
**Result:** Found session `60132e69` (Feb 20) with the exact comparison table:

| CLI | Headless command |
|-----|-----------------|
| Claude Code | `claude --print "prompt"` |
| Codex CLI | `codex exec "prompt"` |
| Cursor Agent | `cursor-agent -p "prompt"` |

### Search 3: Verification via --help
With the binary name confirmed from Engram, we ran `cursor-agent --help` and got the
full flag set:
```
-p, --print          Print responses to console (headless mode)
--trust              Trust workspace without prompting (headless only)
--workspace <path>   Workspace directory to use
--output-format      text | json | stream-json
--sandbox <mode>     enabled | disabled
--approve-mcps       Auto-approve all MCP servers
```

## Final Commands Used

```bash
# Cursor Agent — Engram repo (correction brief work)
cursor-agent -p --trust \
  --workspace /home/prosperitylabs/Desktop/development/engram \
  "$(cat prompts/cursor-engram-tonight.md)"

# Codex — Loopwright repo (watchdog/spawner/test-runner)
codex exec --full-auto --sandbox danger-full-access \
  "$(cat prompts/codex-loopwright-tonight.md)"
```

Both launched in background with logs piped to `prompts/cursor-agent.log` and
`prompts/codex-agent.log`.

## What Made This Case Study Different

Previous case studies showed Engram recovering **configuration that was forgotten**.
This one shows Engram **correcting a wrong assumption in real-time**.

The workflow went:
1. User asks to "kick off agents headlessly"
2. Claude Code (me) initially says "Cursor doesn't have a headless CLI — it's GUI + hooks only"
3. User says "no, cursor has a way to run it, search via engram"
4. `engram search` returns the exact command from 4 days ago
5. `cursor-agent --help` confirms it
6. Both agents launched within 60 seconds

Without Engram, we would have either:
- Stuck with the wrong assumption and only run Claude + Codex (missing Cursor entirely)
- Spent 10+ minutes searching docs, GitHub issues, and prior session JSONL files manually
- Possibly found it via `which cursor-agent` but wouldn't know the correct flags

## Engram Value Demonstrated

| Metric | Value |
|--------|-------|
| Searches needed | 2 |
| Time from question to answer | ~15 seconds |
| Sessions surfaced | 4 (spanning Feb 4 – Feb 24) |
| Wrong assumption corrected | Yes — "Cursor has no headless CLI" → `cursor-agent -p` |
| Agents successfully launched | 2 (both running headless in background) |

## Pattern: Cross-Session Knowledge as Institutional Memory

This is the core Engram value proposition: **knowledge from session A (Feb 4: exploring
Cursor Agent CLI) becomes immediately actionable in session B (Feb 26: launching a
sprint)**. The human didn't need to remember which session, which date, or which file —
a natural language search across 237+ sessions found it instantly.

For teams running multiple AI agents across multiple projects, this is the difference
between "I know we figured this out before" and actually having the answer.
