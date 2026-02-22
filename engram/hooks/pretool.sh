#!/bin/bash
# Engram PreToolUse hook for Claude Code
# Called by Claude Code before Read/Edit/Write tool calls.
# Reads JSON from stdin, passes to engram hook-handle.
# Outputs JSON with additionalContext if file has history.
engram hook-handle
