# Experiment 004: Structured Brief + Query Rewriter + Recall Evaluation

> Date: 2026-03-03
> Status: In Progress
> Branch: `feat/semantic-search`
> Commits: `64de90d` (structured brief), `fc0e4fa` (query rewriter), `24c01b6` (engram_recall)

## Hypothesis

The three features landing on `feat/semantic-search` — structured brief, query rewriter, and engram_recall — work correctly in isolation and together, meeting or exceeding the baselines from Experiments 002 (briefs cut planning time 55%) and 003 (NL search 43% faster).

## Phase 1: Automated Benchmarks

Run: `uv run pytest tests/test_experiment_004.py -v -s`

### Scorecard

| # | Test | Target | Stretch | Result | Notes |
|---|------|--------|---------|--------|-------|
| A | Keyword extraction accuracy | >=80% | >=90% | **98% PASS** | 63/64 checks; only miss: "middleware" capped at 5 keywords |
| B | Synonym expansion | >=75% | >=87% | **100% PASS** | 8/8 keyword sets expanded correctly |
| C1 | Recall intent recall | >=80% | >=92% | **100% PASS** | 12/12 positive phrases detected |
| C2 | Recall intent precision | >=90% | 100% | **100% PASS** | 8/8 negative phrases correctly rejected |
| C3 | Topic keyword accuracy | >=70% | >=85% | **100% PASS** | 22/22 topic keywords extracted |
| D | Rewritten >= Raw FTS | >=60% | >=80% | **100% PASS** | 5/5 queries; raw returns 0 for NL, rewritten finds 30-77 |
| E | Brief quality score | >=6/10 | >=8/10 | **8/10 PASS** | Best: "development" (8/10), missed Decisions section |
| F | Recall E2E accuracy | >=60% | >=80% | **100% PASS** | 5/5 phrases found relevant sessions |
| G1 | Rewriter latency | <5ms | <1ms | **0.004ms PASS** | Hit stretch target by 250x |
| G2 | Brief latency | <2s | <0.5s | **0.466s PASS** | Hit stretch target; 3-run avg on richest project |

**Feature pass/fail:**
- Query Rewriter: A + B + C1 + C2 + G1 all pass -> [x] **PASS**
- Structured Brief: E + G2 pass -> [x] **PASS**
- engram_recall: C3 + F pass -> [x] **PASS**

---

## Phase 2: Manual A/B Brief Test

### Objective

Measure whether the new 5-section structured brief reduces exploration and speeds up a targeted investigation task, compared to a cold-start session.

### Task

> "The `_architecture_patterns()` function in `engram/brief.py` sometimes includes boilerplate. Investigate and fix."

This task was chosen because:
- It targets a real function in the engram codebase
- Requires reading `brief.py`, understanding `BOILERPLATE_PREFIXES`, tracing `_is_boilerplate()` calls
- An agent without context would need to discover where the function is, what "boilerplate" means in this context, and what the filtering logic does
- The structured brief should provide: key files (brief.py is most-modified), recent intent, and architecture decisions

### Setup

#### Pre-requisites

```bash
# Create two isolated worktrees in /tmp
cd ~/Desktop/development/engram
git worktree add /tmp/engram-control feat/semantic-search
git worktree add /tmp/engram-treatment feat/semantic-search
```

#### Session A — Control (no brief)

```bash
# Wait 5 minutes after Session B (cache gap for confound mitigation)
# Start Claude Code WITHOUT engram MCP, no CLAUDE.md context
cd /tmp/engram-control
claude --mcp-config '{}'
```

Paste the task prompt. Let the agent work until it proposes a fix or gives up.

#### Session B — Treatment (with structured brief)

First, generate the brief:
```bash
cd ~/Desktop/development/engram
python -c "
from engram.recall.session_db import SessionDB
from engram.brief import generate_brief
db = SessionDB()
# Use the engram project name from your sessions
brief = generate_brief(db, 'engram', format='markdown')
print(brief)
" > /tmp/engram-treatment/CLAUDE.md
```

```bash
cd /tmp/engram-treatment
claude  # CLAUDE.md will be auto-loaded
```

Paste the same task prompt.

### Metrics

| Metric | Session A (Control) | Session B (Treatment) |
|--------|--------------------|-----------------------|
| Duration (wall clock) | | |
| Total tool calls | | |
| Exploration ratio (reads / total) | | |
| Files read before finding `brief.py` | | |
| Correct fix proposed? (Y/N) | | |
| First correct action within N messages | | |

### Confound Mitigation

- **5-minute cache gap**: Run sessions 5 min apart to avoid model-side caching
- **/tmp isolation**: Both sessions use fresh worktrees, no shared state
- **No engram MCP**: Neither session has access to engram search — tests brief injection only
- **Same branch**: Both worktrees point to `feat/semantic-search`

### Session A Results

```
Duration:
Tool calls:
Files read:
Files read before finding brief.py:
Exploration ratio:
Correct fix:
Notes:
```

### Session B Results

```
Duration:
Tool calls:
Files read:
Files read before finding brief.py:
Exploration ratio:
Correct fix:
Notes:
```

### Phase 2A Verdict

- [ ] Treatment faster than control
- [ ] Treatment used fewer exploration tool calls
- [ ] Treatment found target file sooner
- [ ] Both produced correct fix

---

## Phase 2B: Monra Signup Fix A/B Test

### Objective

Real-world A/B test using an actual production bug (monra signup flow). Measures how many turns and tool calls an agent needs to recover context and identify the fix, with and without engram.

### Task

> "The signup flow is broken — user_type and business_name aren't being passed through createUser to the management Lambda. Debug and fix it."

This task was chosen because:
- It's a real multi-file bug spanning 4 target files across frontend and Lambda layers
- Without context, the agent must discover: which files handle signup, which Lambda functions are involved, and that there's unmerged branch work
- Engram should surface the relevant sessions, key files, and prior decisions

### Setup

#### Session A — Control (cold start, no engram)

```bash
# Use the experiment runner script:
bash ~/Desktop/development/engram/docs/experiments/004-run-experiment.sh a

# Or manually:
git clone --recurse-submodules ~/Desktop/development/monra.app /tmp/monra-control
cd /tmp/monra-control
claude --mcp-config /tmp/004-empty-mcp.json --strict-mcp-config
# Paste the task prompt
```

#### Session B — Treatment (with engram)

```bash
# Wait 5 minutes after Session A (cache gap)
# Use the experiment runner script:
bash ~/Desktop/development/engram/docs/experiments/004-run-experiment.sh b

# Or manually:
git clone --recurse-submodules ~/Desktop/development/monra.app /tmp/monra-engram
cd /tmp/monra-engram
claude  # engram MCP from ~/.claude/settings.json will be loaded
# Paste the same task prompt
```

> **Important**: Verify engram MCP connects successfully before proceeding.
> Claude Code should show engram tools available (no "MCP server failed" message).
> If it fails, check: `which engram`, `engram mcp --help`, and that `~/.local/bin` is on PATH.

### Metrics

| Metric | Session A (Control) | Session B (Engram) |
|--------|--------------------|--------------------|
| Timestamp (start) | | |
| Turn # when agent identifies the 4 target files | | |
| Turn # when agent finds the Lambda function names | | |
| Total tool calls used for exploration | | |
| Discovered unmerged branch work? (Y/N) | | |
| Timestamp of first edit | | |
| Total wall-clock to first edit | | |

### Confound Mitigation

- **5-minute cache gap**: Run sessions 5 min apart to avoid model-side caching
- **/tmp clone isolation**: Both sessions use fresh clones, no shared state
- **Same prompt**: Identical task prompt pasted verbatim
- **Stop at first edit**: Measures context recovery speed, not fix quality

### Session A Results (Run 1 — 2026-03-03)

```
Start time: ~11:47 UTC
Turn # identifying target files: 2 (found handlers.ts quickly via grep)
Turn # finding Lambda names: 1 (found createUser handler directly)
Exploration tool calls: ~8 (Glob, Grep, Read)
Discovered unmerged branch: No
First edit time: ~11:49 UTC
Wall-clock to first edit: ~2m 18s
Notes: Partial fix only — added user_type/business_name to handler parameter pass-through
        in handlers.ts (2 lines). Did NOT find the db.ts wallet_address column issue.
        No MCP servers loaded (control).
```

### Session B Results (Run 1 — 2026-03-03, INVALID)

```
Start time: ~11:50 UTC
Turn # identifying target files: 3 (explored more broadly)
Turn # finding Lambda names: 2
Exploration tool calls: ~12 (Glob, Grep, Read)
Discovered unmerged branch: No
First edit time: ~11:53 UTC
Wall-clock to first edit: ~3m 15s
Notes: INVALID TEST — "1 MCP server failed" at startup. Engram MCP did not load,
        so this was effectively another control session. Agent found a deeper bug
        (wallet_address column stored in wallets table, not users table) and fixed
        db.ts with JOIN query + destructuring. More thorough but no recall advantage.
        Root cause: bash --rcfile skipped .bashrc, potentially losing PATH to engram.
```

### Phase 2B Verdict (Run 1 — INVALID, needs re-run)

- [ ] Engram session found target files sooner — **N/A** (MCP failed)
- [ ] Engram session used fewer exploration calls — **N/A**
- [ ] Engram session discovered unmerged branch work — **N/A**
- [ ] Engram session reached first edit faster — **N/A**

> **Action**: Re-run with fixed `004-run-experiment.sh` (sources .bashrc, pre-flight MCP check).

---

## Phase 3: Manual Recall Test

### Objective

Validate that `engram_recall` MCP tool works in a live Claude Code session — the agent should automatically call `engram_recall` when the user references past work.

### Setup

```bash
# Ensure engram MCP is configured in ~/.claude/settings.json
# Start Claude Code normally
claude
```

### Test Questions

Score each 0-5:
- 0 = No recall attempted
- 1 = Recall attempted but wrong tool/query
- 2 = Recall called, no useful results
- 3 = Recall called, found relevant session but incomplete answer
- 4 = Recall called, correct and project-specific answer
- 5 = Recall called, correct answer with specific details (file paths, commands)

| # | Question | Score | Agent called recall? | Answer quality |
|---|----------|-------|---------------------|----------------|
| 1 | "We already figured out how to do batch OpenAI embeddings. What was the script?" | | | |
| 2 | "How did we fix the vec0 INSERT OR REPLACE issue?" | | | |
| 3 | "What was the command for running the engram MCP server?" | | | |
| 4 | "Remember when we set up the sqlite-vec extension? What were the gotchas?" | | | |
| 5 | "Didn't we already solve the INT8 quantization for embeddings?" | | | |

### Phase 3 Scoring

- Average score: ___/5
- Target: >=3.0/5
- Result: [ ] PASS / [ ] FAIL

---

## Cleanup

```bash
# Remove worktrees
cd ~/Desktop/development/engram
git worktree remove /tmp/engram-control
git worktree remove /tmp/engram-treatment
```

---

## Overall Verdict

| Feature | Pass? | Notes |
|---------|-------|-------|
| Query Rewriter | | A + B + C1 + C2 + G1 |
| Structured Brief | | E + G2 + Phase 2 |
| engram_recall | | C3 + F + Phase 3 |

**Ship decision:** [ ] Ship all three / [ ] Ship with changes / [ ] Block — needs rework
