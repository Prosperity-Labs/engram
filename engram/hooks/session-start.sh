#!/bin/bash
# Engram SessionStart hook for Claude Code
# Auto-generates a slim brief into CLAUDE.md at session start.
# Runs `engram brief --slim` and writes to the project's CLAUDE.md.

# Detect project root from CWD (Claude Code sets this)
PROJECT_ROOT="${PWD}"
CLAUDE_MD="${PROJECT_ROOT}/CLAUDE.md"

# Generate slim brief and write to CLAUDE.md
# If engram fails (no data, not installed), silently skip
engram brief --slim --output "${CLAUDE_MD}" 2>/dev/null || true
