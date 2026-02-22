# Experiment 001: PreToolUse Hook A/B Test

> Date: 2026-02-22
> Status: In Progress

## Hypothesis

Engram's PreToolUse hook reduces warmup time by injecting file context before Read/Edit/Write calls, eliminating cross-session rediscovery.

## Setup

- **Baseline (no hooks):** Fresh Claude Code session in monra-app, asked "what was the feature that we planned for migration from front-end to alchemy so we reduce reliance?"
- **Treatment (with hooks):** Same question, with `engram hooks install --project` + `engram brief --slim > CLAUDE.md`

## Baseline Result

- Claude Code found the answer after ~1 minute of exploration
- Session used Grep/Glob/search tools, NOT Read/Edit — so the hook would not have fired anyway
- The question was answerable from search, not from reading specific files

## Key Insight

The PreToolUse hook (Layer 2) only fires on Read/Edit/Write. For discovery/search queries, it has zero effect. The slim brief (Layer 1 — CLAUDE.md) is what would help here, since it's injected at session start.

This reveals a gap: the hook addresses file-level context ("what happened to this file before?") but NOT project-level recall ("what features were planned?"). That's the slim brief's job — and the current slim brief doesn't include feature/planning history.

## Observations

1. `engram search "alchemy webhook migration"` found relevant results from the DB in <1 second
2. The baseline session (`1b6a94b5`) had 0 file reads — pure search-based exploration
3. Hooks were correctly installed in `.claude/settings.json` but never triggered for baseline

## Run 1: No Artifacts (e0fd98ab)

Session `e0fd98ab-fb51-4a60-8580-90369bc183d5` — hooks installed but artifacts table empty.

| Tool | Count | Details |
|------|-------|---------|
| Read | 3 | task_plan.md, progress.md, SESSION_2026_02_20_BALANCE_FIX.md |
| Grep | 5 | Various alchemy/webhook pattern searches |
| Bash | 2 | `ls` on feature-planning/ and .cursor/plans/ |

**Duration:** 70s | **Messages:** 29 | **Result:** Found answer

**Hook behavior:** Fired on 3 Read calls but `file_context()` returned `None` — artifacts table was empty. `engram install` indexed sessions/messages but did not extract artifacts.

**Fix applied:** `engram install` now auto-runs artifact extraction. Also ran `engram artifacts --extract` (16,249 artifacts from 283 sessions).

## Run 2: With Artifacts (f06c4b0f)

Session `f06c4b0f-3629-48ed-92a1-cccfeff83cd4` — hooks installed AND artifacts populated.

| Tool | Count | Details |
|------|-------|---------|
| Read | 4 | task_plan.md, progress.md, PLAN_WEBHOOK_DRIVEN_LINK_TRANSFER_STATUS.md, SESSION_2026_02_20_BALANCE_FIX.md |
| Grep | 3 | Alchemy/migration pattern searches |
| Glob | 2 | feature-planning/, docs/plans/ |

**Duration:** 79s | **Messages:** 31 | **Result:** Found answer

**Hook behavior:** Fired on all 4 Read calls. `pretool.sh` confirmed working — returns `additionalContext` with file history. Claude Code doesn't log hook output in JSONL, so we can't directly verify what the model saw, but the hook produced valid output.

## Side-by-Side Comparison

```
                   Baseline (e0fd98ab)    Treatment (f06c4b0f)
  Duration:        70s                    79s
  Messages:        29                     31
  Tool calls:      10                     10
  Read:             3                      4
  Grep:             5                      3
  Glob:             0                      2
  Bash:             2                      0
  Hook output:     None (no artifacts)    Context injected (4x)
  Found answer:    Yes                    Yes
```

**Behavioral difference:** Treatment used fewer Greps (3 vs 5) and more targeted Reads (4 vs 3). The hook may have given the model confidence to read files directly rather than grep blindly. However, n=1 — not conclusive.

**Limitation:** Claude Code does not log `additionalContext` from hooks in the JSONL file. We can verify the hook produces output (via manual pipe test) but cannot directly confirm the model received it during the session.

## Conclusions

1. **Hook fires correctly** on Read/Edit/Write — the matcher pattern works
2. **Pipeline gap fixed:** `engram install` now auto-extracts artifacts so hooks have data
3. **Hook output verified** via manual test — produces valid `additionalContext` JSON
4. **No measurable speedup** on this recall task (70s vs 79s) — but task type doesn't match hook's strength
5. **Search-based queries** (Grep/Glob) bypass hooks — Layer 1 (slim brief) is needed for recall tasks
6. **JSONL doesn't log hook output** — observability gap for experiments

## Next Steps

- [ ] Run experiment with a **file-editing task** to trigger hooks on Edit/Write (hook's intended use case)
- [ ] Measure: does hook context reduce re-reads of files with known history?
- [ ] Consider: should Layer 1 (slim brief) include "recent feature designs" section?
- [ ] Consider: should hooks also fire on Grep/Glob for broader coverage?
- [x] ~~Fix: `engram install` should auto-extract artifacts~~ (done)

## How to Revert

Remove hooks from monra project:
```bash
# Option 1: Delete the project settings file
rm /home/prosperitylabs/Desktop/development/monra.app/.claude/settings.json

# Option 2: Edit and remove just the hooks section
# Open .claude/settings.json, delete the "hooks" key
```
