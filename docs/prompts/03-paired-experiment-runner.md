## Build paired experiment runner

Create engram/experiment/runner.py

Usage:
```bash
engram experiment run \
    --task "fix the webhook validation" \
    --project monra-core \
    --cache-gap 300
```

What it does:
1. Creates two git worktrees from current HEAD
2. Runs CONTROL: spawns claude with engram proxy --no-enrich
   on worktree A. Records session_id.
3. Waits --cache-gap seconds (default 300)
4. Runs ENRICHED: spawns claude with engram proxy (enrichment on)
   on worktree B. Records session_id.
5. Both runs use --max-turns 50 as safety limit
6. After both complete, queries session_metrics for both session_ids
7. Prints comparison:

```
Experiment: "fix the webhook validation" on monra-core

                    Control    Enriched    Delta
Turns to edit    47         5           -89%
Exploration $    $4.80      $0.60       -87%
Total turns      82         23          -72%
Total cost       $8.40      $2.10       -75%
Outcome          success    success     =
```

8. Saves result to experiments table
9. Cleans up worktrees

Integrate with Loopwright's existing worktree and spawning logic.
Don't rebuild what exists.

### Dependencies
- Requires prompt #02 (session_metrics table) to be implemented first
- Requires prompt #01 (brief quality) for enrichment to be meaningful
- Execute sequentially: #01 → #02 → #03

### Design Notes
- Cache gap ensures cold cache for fair comparison
- Git worktrees isolate file system side effects between runs
- --max-turns prevents runaway sessions
- Both runs go through the same proxy instance on different ports (or same port with enrichment toggled)
- Need to figure out how to programmatically pass a task to Claude Code (--message flag? stdin pipe?)
