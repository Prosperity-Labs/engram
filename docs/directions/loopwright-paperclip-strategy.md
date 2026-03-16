# Loopwright ↔ Paperclip ↔ Engram: Strategic Direction

*2026-03-16*

## The thesis

We have three tools that each do one thing well:

- **Paperclip** — task management, agent coordination, UI. 649+ PRs of battle-tested code.
- **Loopwright** — self-correcting execution loops. Spawn agent → test → correct → retry.
- **Engram** — measurement. Proxy sees every API call, computes session metrics, injects enrichment.

Wired together: Paperclip decides *what* to work on. Loopwright decides *how* to execute it. Engram measures *whether the context we inject actually helps*.

This is a closed measurement loop. That's the moat.

## What we're actually proving

The enrichment hypothesis: injecting context from past sessions (project briefs, danger zones, co-change clusters, key decisions) into an agent's system prompt reduces exploration cost and increases task completion rate.

Before Loopwright integration, our A/B data was confounded — enriched and baseline runs happened on different projects at different times. Now we can run the **same task, same git state, same model** — once enriched, once baseline — and compare directly.

If enrichment helps: we have proof that Engram's context engineering creates measurable value.
If it doesn't: we learn what kinds of context are noise and can cut them.

Either outcome is progress.

## What we built (2026-03-16)

| Component | What it does |
|-----------|-------------|
| `paperclip-entry.ts` | Bridges Paperclip → Loopwright. Fetches task, runs loop, posts progress comments. |
| `experiment.ts` | A/B runner. Same task, two worktrees, cache gap, structured comparison. |
| `multi-agent.ts` | Claude vs Codex vs Cursor on same task, parallel worktrees. |
| `session_metrics` extensions | `agent_type`, `correction_cycles`, `loop_outcome` columns. |

Zero Paperclip code changes. Everything uses existing `process` adapter.

## Strategic sequence

### Phase 1: Prove enrichment works (next 2 weeks)

1. Run 10-20 A/B experiments on real tasks across engram, paperclip, and loopwright repos
2. Accumulate `session_metrics` data with clean enriched/baseline separation
3. Look for signal in: turns-to-first-edit, exploration cost, total cost, correction cycles
4. Statistical significance requires ~15 paired observations at p<0.05

Key question answered: **does context injection measurably reduce agent cost or improve outcomes?**

### Phase 2: Context quality iteration (weeks 3-4)

If enrichment shows signal:
- Which brief sections matter? (danger zones? co-change clusters? key decisions?)
- Ablation study: run experiments with individual sections removed
- Brief length vs. value: is the full brief better than just "top 5 files + last 3 errors"?

If enrichment shows no signal:
- The brief is likely too thin or too generic
- Try richer context: full error traces, recent diffs, file-level summaries
- Try structural context: Memgraph PageRank, community clusters

### Phase 3: Multi-agent intelligence (month 2)

- Which agent types benefit most from enrichment? (Claude may respond differently than Codex)
- Use multi-agent runner to compare across models systematically
- Build agent selection heuristic: "for Python test fixes, Codex is 30% cheaper"

### Phase 4: Forward simulation (month 3+)

- Pre-flight context selection: before running a task, predict which context will help
- Session replay: reproduce completed session starting states, test different enrichment
- Autonomous experiment scheduling: Paperclip creates experiment issues automatically

## The business angle

If we prove enrichment works with statistical rigor:
- **Engram-as-a-service**: companies install the proxy, get context injection that measurably reduces their AI coding costs
- **Pricing**: percentage of cost savings (we can measure the delta)
- **Data network effect**: more sessions → richer briefs → better context → more savings
- **Loopwright**: the execution layer that turns "assign a task" into "get a passing PR"

The proxy is the wedge. Measurement is the proof. Paperclip is the control plane.

## Risks

1. **Enrichment might not help** — context could be noise at current brief quality. Mitigation: iterate on brief content, try different granularities.
2. **Cache gap may be insufficient** — API-side caching could still confound results. Mitigation: randomize run order (A first vs B first), increase gap.
3. **Task variance** — some tasks are inherently easier. Mitigation: paired design (same task both ways) controls for this.
4. **Agent non-determinism** — same prompt, different results. Mitigation: run each experiment 3x, report medians.

## Key metrics to track

| Metric | Why it matters |
|--------|---------------|
| `turns_to_first_edit` | How quickly the agent starts doing useful work |
| `exploration_cost_usd` | $ spent reading before writing — enrichment should reduce this |
| `correction_cycles` | Self-correction rounds — enrichment should reduce first-try failures |
| `total_cost_usd` | Bottom line: did enrichment save money? |
| `loop_outcome` | Pass rate: did enrichment increase success? |

## Files

- Plan: `docs/prompts/04-loopwright-paperclip-integration.md`
- Loopwright branch: `feat/loopwright-paperclip`
- Engram schema: `engram/proxy/schema.sql`
- Metrics: `engram/proxy/metrics.py`
