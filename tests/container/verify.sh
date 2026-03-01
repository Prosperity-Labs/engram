#!/bin/bash
# Container verification for engram auto-sync with real session data.
# Uses actual A/B experiment sessions from experiment 003.
set -uo pipefail

PASS=0
FAIL=0

check() {
    local desc="$1"
    shift
    if eval "$@" >/dev/null 2>&1; then
        echo "  PASS: $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $desc"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== Engram Auto-Sync: Real Session Container Test ==="
echo ""

# ── Step 1: CLI works ──
echo "Step 1: CLI availability"
check "engram binary exists" "which engram"
check "engram --help works" "engram --help"

# ── Step 2: Index real sessions ──
echo ""
echo "Step 2: Index real A/B experiment sessions"
OUTPUT=$(engram install 2>&1)
echo "$OUTPUT" | head -8
SESSION_COUNT=$(echo "$OUTPUT" | grep -oP '\d+ sessions indexed' | grep -oP '\d+')
check "indexed sessions" "test '$SESSION_COUNT' -ge 1"

# ── Step 3: Quiet mode ──
echo ""
echo "Step 3: Quiet mode (--quiet)"
QUIET_OUTPUT=$(engram install --quiet 2>&1)
check "quiet produces no output" "test -z '$QUIET_OUTPUT'"

# ── Step 4: Incremental ──
echo ""
echo "Step 4: Incremental (second run skips)"
OUTPUT2=$(engram install 2>&1)
check "skips already indexed" "echo '$OUTPUT2' | grep -q 'already indexed'"

# ── Step 5: Search for headless agent commands ──
echo ""
echo "Step 5: Search — headless agent commands (the core engram demo)"
SEARCH1=$(engram search "cursor-agent headless" 2>&1)
echo "$SEARCH1" | head -8
check "finds cursor-agent" "echo '$SEARCH1' | grep -qi 'cursor-agent\|headless'"

engram search "codex exec" 2>&1 | tee /tmp/search2.txt | head -8
check "finds codex exec" "sed 's/\x1b\[[0-9;]*m//g' /tmp/search2.txt | grep -qi codex"

# ── Step 6: Search for Cursor CLI flags ──
echo ""
echo "Step 6: Search — specific flags from session history"
SEARCH3=$(engram search "print force output-format" 2>&1)
check "finds CLI flags" "echo '$SEARCH3' | grep -qi 'print\|force\|output'"

# ── Step 7: SessionStart hook ──
echo ""
echo "Step 7: SessionStart hook"
mkdir -p /tmp/test-project && cd /tmp/test-project
check "hook exits 0" "bash /app/engram/hooks/session-start.sh"
check "hook is idempotent" "bash /app/engram/hooks/session-start.sh"

# ── Step 8: Knowledge base stats ──
echo ""
echo "Step 8: Knowledge base stats"
STATS=$(engram insights --json 2>&1)
check "insights returns valid JSON" "echo '$STATS' | python3 -c 'import sys,json; d=json.load(sys.stdin); assert d'"

# ── Step 9: Add new session, verify incremental pick-up ──
echo ""
echo "Step 9: New session detection"
echo '{"type":"user","timestamp":"2026-02-28T10:00:00Z","message":{"role":"user","content":[{"type":"text","text":"What hooks does engram support?"}]}}' > /root/.claude/projects/test-project/new-session-after-install.jsonl
echo '{"type":"assistant","timestamp":"2026-02-28T10:00:01Z","message":{"role":"assistant","content":[{"type":"text","text":"PreToolUse, SessionStart, and SessionEnd hooks."}],"usage":{"input_tokens":80,"output_tokens":15}}}' >> /root/.claude/projects/test-project/new-session-after-install.jsonl

OUTPUT3=$(engram install 2>&1)
check "picks up new session" "echo '$OUTPUT3' | grep -q '1 sessions indexed'"

# Verify the new session is searchable
SEARCH4=$(engram search "PreToolUse SessionStart" 2>&1)
check "new session is searchable" "echo '$SEARCH4' | grep -qi 'PreToolUse\|SessionStart'"

# ── Summary ──
echo ""
echo "================================"
echo "Results: $PASS passed, $FAIL failed"
echo "================================"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
