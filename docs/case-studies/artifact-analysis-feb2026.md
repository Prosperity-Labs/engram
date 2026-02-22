# Case Study: What 13,881 Artifacts Reveal About Agent Behavior

> **Date:** 2026-02-22
> **Dataset:** 246 sessions, 45K messages, 13,881 artifacts across 15+ projects
> **Tool:** Engram v0.2.0 artifact extractor + SQL analytics

## How This Analysis Was Produced

Every AI agent session (Claude Code, Codex, Cursor) logs tool calls — Read, Edit, Write, Bash, Glob, Grep, MCP tools. These logs sit as raw JSONL files in `~/.claude/projects/`. Engram indexes them into SQLite with FTS5, then the **artifact extractor** parses each tool call into a structured record:

```
tool_use:Read(file_path=/src/handlers.ts) → { artifact_type: "file_read", target: "/src/handlers.ts" }
tool_use:Edit(file_path=/src/handlers.ts) → { artifact_type: "file_write", target: "/src/handlers.ts" }
tool_use:Bash(command=npm run deploy)     → { artifact_type: "command",    target: "npm run deploy" }
```

13,881 of these records across 246 sessions. Then simple SQL — `GROUP BY`, `COUNT`, `HAVING` — reveals patterns that are invisible in the raw logs.

**Key insight:** The data was always there. Structuring it is what makes it queryable.

## The Dataset

| Type | Count | % |
|------|-------|---|
| command | 5,581 | 40.2% |
| file_read | 3,621 | 26.1% |
| error | 1,924 | 13.9% |
| file_write | 1,453 | 10.5% |
| file_create | 731 | 5.3% |
| api_call | 571 | 4.1% |
| **Total** | **13,881** | **100%** |

## Finding 1: 24% of All File Reads Are Redundant

```sql
SELECT SUM(times_read - 1) as wasted FROM (
    SELECT COUNT(*) as times_read
    FROM artifacts WHERE artifact_type = 'file_read'
    GROUP BY session_id, target
    HAVING times_read > 1
)
```

**Result:** 868 / 3,621 file reads (24.0%) are re-reads of files the agent already saw in the same session.

The worst case: `handlers.ts` was read **40 times in a single session**. The agent loses context through compression, forgets it already read the file, and re-discovers it. Each re-read costs tokens — the file content gets sent back in full every time.

**Implication:** A session-start brief listing "files you've already read in this project" could eliminate ~24% of file read tokens. This is the core value proposition of `engram brief`.

## Finding 2: Projects Have Wildly Different Productivity Rates

```sql
SELECT project,
    SUM(CASE WHEN artifact_type IN ('file_write','file_create') THEN 1 ELSE 0 END) as mutations,
    SUM(CASE WHEN artifact_type = 'error' THEN 1 ELSE 0 END) as errors,
    COUNT(*) as total
FROM artifacts a JOIN sessions s ON s.session_id = a.session_id
GROUP BY project HAVING total > 50
```

| Project | Productivity | Error Rate | Sessions |
|---------|-------------|------------|----------|
| compadre-analysis | 42% | 1% | 3 |
| collabberry-agents | 31% | 5% | 3 |
| music-nft-platform | 22% | 13% | 21 |
| monra-app | 12% | 13% | 24 |
| monra-core | 11% | 19% | 31 |
| claude-mem | 0% | 99% | 17 |

**Productivity** = (file_write + file_create) / total actions. How much of the agent's effort produces code changes vs. exploration, errors, and commands.

`monra-core` has a 19% error rate and only 11% productivity — for every 10 actions, roughly 2 are errors and only 1 is an actual code change. Compare with `compadre-analysis` at 42% productivity and 1% errors.

`claude-mem` is the extreme: 17 sessions, zero file writes, 179 errors. Every session hit the same blocker and churned without producing anything.

**Implication:** Projects with low productivity and high error rates would benefit most from better upfront context, architecture docs, or even a "don't bother — this project has a recurring blocker" warning.

## Finding 3: `handlers.ts` Is a Complexity Magnet

| Metric | Count |
|--------|-------|
| Total reads | 133 |
| Total edits | 67 |
| Max reads in one session | 40 |
| Max edits in one session | 16 |

This single file accounts for more agent activity than most entire projects. It's a god-file — too large, too many responsibilities, touched by every flow. The agent keeps coming back to it because understanding the system means understanding this file.

**Implication:** Refactoring god-files doesn't just improve code quality — it directly reduces agent token cost. Smaller, focused files get read once and understood. God-files get re-read constantly because the agent can't hold the whole thing in context.

## Finding 4: Edit Churn Reveals Trial-and-Error Loops

```sql
SELECT target, COUNT(*) as edits
FROM artifacts WHERE artifact_type = 'file_write'
GROUP BY session_id, target
HAVING edits >= 3
ORDER BY edits DESC
```

| File | Edits in 1 Session |
|------|--------------------|
| personal-knowledge-graph/pkg/cli.py | 22 |
| music-nft-platform/widget/src/ui/styles.css | 21 |
| personal-knowledge-graph/README.md | 20 |
| monra-core/TransactionLifecycleService.ts | 18 |
| monra-core/TransferService.ts | 18 |

22 edits to a single file in one session = write → test → fail → rewrite, repeated 22 times. The agent is iterating by trial and error instead of getting it right upfront.

**Implication:** CSS files and service files with complex business logic see the most churn. Better error context ("last time you edited this file, the test failed because of X") would cut iteration loops.

## Finding 5: Testing Is Only 3.6% of Commands

| Command Category | Count | % |
|-----------------|-------|---|
| git | 980 | 17.6% |
| ls/explore | 849 | 15.2% |
| dev server | 277 | 5.0% |
| test | 203 | 3.6% |
| build | 177 | 3.2% |
| install | 176 | 3.2% |
| deploy | 170 | 3.0% |
| other | 2,749 | 49.3% |

The agent deploys nearly as often as it tests (170 vs 203). `git` operations and `ls/explore` dominate — the agent spends more time navigating and version-controlling than building or verifying.

**Implication:** Agents are under-testing. A brief could include "run tests before deploying" as a project-specific instruction, or flag when a session has zero test commands.

## Finding 6: MCP Tools Are Database-Heavy

| MCP Tool | Calls |
|----------|-------|
| postgres.run_dql_query | 177 |
| noodlbox.query_with_context | 54 |
| excalidraw.delete_element | 44 |
| playwright.browser_click | 33 |
| postgres.get_columns | 26 |
| notebooklm.source_add | 22 |
| noodlbox.raw_cypher_query | 20 |

Postgres queries dominate API calls — the agent is doing significant data exploration through MCP. Noodlbox code search (54 queries) and Excalidraw diagramming (44 operations) follow.

**Implication:** Projects with heavy database interaction might benefit from cached schema descriptions in the brief, reducing the need for `get_columns` calls.

## Finding 7: Error-Prone Sessions Are Identifiable

| Session | Project | Errors | Total | Error % |
|---------|---------|--------|-------|---------|
| 82b957bc | app | 81 | 532 | 15.2% |
| 5b6fa781 | monra-app | 78 | 629 | 12.4% |
| 1e28bfa0 | monra-core | 76 | 187 | 40.6% |
| 46971622 | monra-app | 69 | 468 | 14.7% |
| 3a4a4ff9 | stakecommit | 59 | 228 | 25.9% |
| b9918d46 | claude-mem | 53 | 53 | 100.0% |

Session `1e28bfa0` had a 40.6% error rate — nearly half of all actions were errors. Session `b9918d46` was 100% errors — 53 actions, every single one an error.

**Implication:** Error patterns cluster by project, not by session. `monra-core` and `stakecommit` consistently produce high-error sessions. Project-level error history in the brief would help the agent avoid known failure modes.

---

## Bottom Line

The biggest token savings come from:

1. **Eliminating re-reads** (24% waste) — tell the agent what it already knows
2. **Giving error-prone projects better upfront context** — prevent the same errors across sessions
3. **Breaking up god-files** like `handlers.ts` — smaller files = fewer re-reads = lower cost

This is exactly what `engram brief` is designed to address. The data validates the feature.

## How to Reproduce

```bash
# Index all sessions
engram install

# Extract artifacts
engram artifacts --extract

# Run queries against ~/.config/engram/sessions.db
sqlite3 ~/.config/engram/sessions.db "SELECT artifact_type, COUNT(*) FROM artifacts GROUP BY artifact_type"
```

## Technical Note: The Bug That Made This Possible

The artifact extractor initially had **8.6% coverage** — it could only parse 1,161 out of 13,424 tool messages. The root cause: Claude Code's adapter stores tool call parameters as Python dict literals with single quotes (`{'file_path': '/src/foo.ts'}`), but the parser used `json.loads()` which requires double quotes.

Adding an `ast.literal_eval` fallback fixed coverage to **89.1%** (13,881 artifacts) — a 4.5x improvement. Without this fix, none of the analysis above would have been meaningful.
