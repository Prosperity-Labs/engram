#!/bin/bash
# Engram SessionStart hook for Claude Code
# 1. Index any new sessions (incremental — skips already-indexed)
# 2. Auto-generate a slim brief into CLAUDE.md
#
# Both steps are silent on failure so they never block session start.

# Step 1: Incremental index (new sessions only, typically <2s)
engram install --quiet 2>/dev/null || true

# Step 2: Generate slim brief and write to CLAUDE.md
PROJECT_ROOT="${PWD}"
CLAUDE_MD="${PROJECT_ROOT}/CLAUDE.md"
engram brief --slim --output "${CLAUDE_MD}" 2>/dev/null || true
