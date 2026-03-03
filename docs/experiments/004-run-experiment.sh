#!/usr/bin/env bash
# Experiment 004: Monra Signup Fix A/B Test
# Usage: bash docs/experiments/004-run-experiment.sh [session-a|session-b]
# Recording: Use OBS Studio to capture the full Kitty window

set -euo pipefail

MONRA_REPO="$HOME/Desktop/development/monra.app"
PROMPT='The signup flow is broken — user_type and business_name aren'\''t being passed through createUser to the management Lambda. Debug and fix it.'
EMPTY_MCP_CONFIG="/tmp/004-empty-mcp.json"

# Pre-flight: create empty MCP config for Session A (disables all MCP servers)
echo '{"mcpServers":{}}' > "$EMPTY_MCP_CONFIG"

preflight_engram() {
    echo "Pre-flight: checking engram MCP server..."
    if ! command -v engram &>/dev/null; then
        echo "ERROR: 'engram' not found on PATH"
        echo "  Install with: uv tool install engram"
        return 1
    fi
    if timeout 5 bash -c 'echo "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{},\"clientInfo\":{\"name\":\"test\",\"version\":\"1.0\"}}}" | engram mcp 2>/dev/null | head -c1' | grep -q '{'; then
        echo "  engram MCP server: OK"
    else
        echo "  WARNING: engram MCP server did not respond to initialize"
        read -rp "Continue anyway? [y/N] " yn
        [[ "$yn" =~ ^[Yy] ]] || return 1
    fi
}

session_a() {
    echo "=== SESSION A: Control (no recall) ==="

    rm -rf /tmp/monra-control
    git clone --recurse-submodules "$MONRA_REPO" /tmp/monra-control
    cd /tmp/monra-control

    echo "Worktree ready. Launching Claude Code (no MCP servers)..."
    echo ""
    claude --mcp-config "$EMPTY_MCP_CONFIG" --strict-mcp-config "$PROMPT"
}

session_b() {
    echo "=== SESSION B: Treatment (with recall) ==="

    preflight_engram || return 1

    rm -rf /tmp/monra-engram
    git clone --recurse-submodules "$MONRA_REPO" /tmp/monra-engram
    cd /tmp/monra-engram

    echo "Worktree ready. Launching Claude Code (with engram)..."
    echo ""
    claude "$PROMPT"
}

case "${1:-}" in
    session-a|a)
        session_a
        ;;
    session-b|b)
        session_b
        ;;
    *)
        echo "Experiment 004: Monra Signup Fix A/B Test"
        echo ""
        echo "Usage:"
        echo "  $0 a    # Session A: control (no engram)"
        echo "  $0 b    # Session B: treatment (with engram)"
        echo ""
        echo "Setup:"
        echo "  1. Start OBS recording"
        echo "  2. kitty --start-as fullscreen --session ~/Desktop/development/engram/docs/experiments/004-kitty-session.conf"
        echo "  3. Left pane:  $0 a"
        echo "  4. Wait 5 minutes"
        echo "  5. Right pane: $0 b"
        echo "  6. Stop OBS when both finish"
        ;;
esac
