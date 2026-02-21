# Case Study: Recovering Multi-Agent Auth Setup via Engram Search

**Date:** 2026-02-21
**Context:** OpenClaw multi-agent pipeline — 2 of 3 agents failing auth

## Problem

Running `run-multi.sh` with 3 agents (Claude, Codex, Cursor) in Docker containers.
Codex worked. Claude and Cursor failed with auth errors. We knew the setup had worked
previously but couldn't remember the exact configuration.

## How Engram Found It

### Search 1: Broad keyword search
```bash
engram search "codex cursor headless agent CLI auth setup"
```
**Result:** Found session `60132e69` (the OpenClaw setup session from Feb 20) with a
comparison table of all three agent CLIs — packages, SDK names, headless commands, and
auth methods.

### Search 2: Cursor headless details
```bash
engram search "headless" --limit 15
```
**Result:** Found session `a9012f1f` (from Feb 4) — the original Cursor Agent exploration
session. Key findings:
- `-p, --print` enables headless/non-interactive mode
- `--workspace <path>` points to specific worktree
- `--output-format json|stream-json` for structured output
- `--approve-mcps` auto-approves MCP servers
- Successful headless test: `cursor-agent -p "Create a file..."` worked

### Search 3: Docker multi-agent setup
```bash
engram search "openclaw docker claude codex cursor parallel"
```
**Result:** Found the exact Docker commands from session `60132e69`:
```bash
# Claude Code
docker exec openclaw-engram claude --dangerously-skip-permissions --max-turns 40 'task'
# Codex CLI
docker exec openclaw-engram codex exec --full-auto 'task'
# Cursor Agent
docker exec openclaw-engram cursor-agent -p --force 'task'
```

## What We Learned

The working auth configuration was documented in `LEARNINGS.md` (which we also found):
- Auth dirs mounted read-only from host: `~/.claude`, `~/.codex`, `~/.cursor`
- Cursor Agent needs either `cursor-agent login` (interactive) or `CURSOR_API_KEY` env var
- Claude Code needs valid OAuth tokens in `~/.claude/.credentials.json`
- Codex uses ChatGPT+ OAuth tokens from `~/.codex/auth.json`

## Root Cause of Failures

| Agent | Error | Root Cause |
|-------|-------|------------|
| Claude | Container hangs, no output | `~/.claude.json` mount missing or stale OAuth tokens |
| Cursor | "Authentication required" | `cursor-agent login` not run in container, no `CURSOR_API_KEY` |
| Codex | Works | ChatGPT+ OAuth tokens still valid |

## FTS Gotcha Discovered

Engram's FTS5 search breaks on certain queries containing hyphens — the SQLite FTS5
tokenizer interprets hyphens as column references, causing `OperationalError: no such column`.

Examples that break:
- `"codex exec full-auto sandbox"` → fails on `auto`
- `"npm install openai codex cursor-agents"` → fails on `agents`

Workaround: Use simpler terms without hyphens, or quote phrases.
This is a known FTS5 limitation — needs a fix in `session_db.py` to escape or quote user input.

## Time Saved

Without engram: Would have had to manually search through `~/.claude/projects/` JSONL
files (237 sessions, 41K+ messages) or re-discover the setup from scratch.

With engram: **3 searches, under 30 seconds** to find the exact Docker commands, CLI
flags, and auth configuration from sessions spanning Feb 4 to Feb 20.
