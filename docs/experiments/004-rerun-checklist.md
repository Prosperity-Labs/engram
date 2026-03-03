# Experiment 004 Re-run Checklist (2026-03-04)

## Pre-flight
- [ ] Ensure `engram` is on PATH: `which engram`
- [ ] Test MCP server starts: `timeout 3 engram mcp`
- [ ] Verify monra.app repo exists: `ls ~/Desktop/development/monra.app/monra-core`

## Run
```bash
# Session A (control, no engram)
bash ~/Desktop/development/engram/docs/experiments/004-run-experiment.sh a

# Inside recording:
#   claude --mcp-config /tmp/004-empty-mcp.json --strict-mcp-config
#   Paste: The signup flow is broken — user_type and business_name aren't being passed through createUser to the management Lambda. Debug and fix it.

# Wait 5 minutes

# Session B (treatment, with engram)
bash ~/Desktop/development/engram/docs/experiments/004-run-experiment.sh b

# Inside recording:
#   claude
#   Verify: NO "MCP server failed" message
#   Paste same prompt
```

## After
- [ ] Replay: `asciinema play docs/experiments/recordings/004-session-a.cast`
- [ ] Replay: `asciinema play docs/experiments/recordings/004-session-b.cast`
- [ ] Ask Claude to analyze both recordings and fill in Phase 2B results
