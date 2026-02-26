# Engram Direction — Measure, Don't Build

> Decided: 2026-02-23
> Status: Active — tracking phase

## Decision

Stop building features. Three context systems are live on monra.app. Measure which ones actually help over the next few weeks, then decide what (if anything) is worth keeping.

## What's Live

### 1. Engram (our system)
- **CLAUDE.md auto-brief** via SessionStart hook — refreshes every session
- **PreToolUse hook** — injects file history before Read/Edit/Write
- **Data**: 290 sessions, 52K messages, 16K artifacts in SQLite + FTS5
- **Proven**: 55% faster planning in experiment 002 (cache-confounded, n=2)
- **Brief fixes shipped**: Key Decisions filtered, Danger Zones use sequence proximity, filenames show parent dir

### 2. Claude-mem (thedotmack plugin, v9.0.5)
- **PostToolUse hook** — captures AI-curated observations on every tool call
- **SessionStart hook** — injects context at session start
- **Worker**: systemd service on port 37777, auto-starts on boot
- **Data**: 585 observations, 2M discovery tokens, vector search via ChromaDB
- **Claims**: 10x token savings via progressive disclosure
- **Cost**: ~3,500 tokens per observation (AI summarization)

### 3. Noodlbox (MCP plugin)
- **MCP tools** — agent calls on-demand for code understanding
- **Data**: 4 repos analyzed (monra.app: 788 MB knowledge graph)
- **103 tool calls** to date (58 semantic search, 22 cypher, 20 symbol context)
- **Cost**: 0 per session (only costs tokens when agent actively queries)

## Baseline Metrics (2026-02-23)

See `docs/baseline-2026-02-23.md` for full numbers. Key baseline:

```
monra-app exploration ratio: 29%
Global cache efficiency: 85%
Claude-mem observations: 585
Claude-mem weekly rate: ~90 obs/week
Noodlbox tool calls: 103 total
```

## How to Measure

After every 5-10 sessions:
```bash
engram stats --project monra-app          # exploration % target: <20%
engram costs --limit 10                   # input tokens per session
engram insights                           # cache efficiency target: >90%
curl -s http://127.0.0.1:37777/api/stats  # claude-mem observation count
```

What to look for:
- **Exploration % dropping** = brief is reducing blind search
- **Input tokens dropping** = context injection saving tokens
- **Claude-mem growing steadily** = observations being captured
- **Noodlbox calls growing** = agent using code graph

## What We WON'T Build

- No MCP server for Engram (claude-mem already has one)
- No FUSE filesystem (experiment 002 proved models read files regardless)
- No vector search (claude-mem already has ChromaDB)
- No web UI (claude-mem already has one)
- No product (the market has claude-mem at 345 stars, Noodlbox with funding)

## What We Might Do (data-dependent)

- If exploration % doesn't drop → brief isn't helping, remove it
- If claude-mem observations plateau → hooks aren't firing, debug
- If noodlbox calls are flat → agent doesn't find it useful
- If one system clearly dominates → consider removing the others to reduce hook overhead

## Competitors Analyzed

| System | Approach | Status |
|--------|----------|--------|
| claude-code-memory (tiiny.site) | DIY tutorial: FastAPI + SQLite FTS5 + UserPromptSubmit hook | Not a product, just a recipe. Claims 80% token savings via FTS5 snippets vs reading full messages. |
| claude-mem (thedotmack) | Plugin: AI-curated observations + MCP tools + vector search | Installed and active. 345 GitHub stars, AGPL license. |
| Engram (Gentleman-Programming) | Go binary: agent-driven memory curation + MCP server | Different project, same name. 345 stars, MIT license. |
| Noodlbox | Code knowledge graph via MCP | Installed and active. Funded startup, beta product. |

## Files Changed in This Session

- `engram/brief.py` — Key Decisions: role=assistant filter, min length, boilerplate+JSON exclusion. Danger Zones: sequence proximity (±10) instead of session-level. Filenames: `_short_path()` shows parent/name.
- `engram/hooks/__init__.py` — `install_hook(auto_brief=True)` adds SessionStart hook. `generate_hook_config(include_session_start=True)`.
- `engram/hooks/session-start.sh` — New script, runs `engram brief --slim --output CLAUDE.md`
- `engram/cli.py` — `--auto-brief` flag on `engram hooks install`
- `monra.app/.claude/settings.json` — PreToolUse + SessionStart hooks active
- `~/.config/systemd/user/claude-mem-worker.service` — Fixed ExecStart path, now auto-starts

## How to Resume

1. Read this file
2. Read `docs/baseline-2026-02-23.md` for full baseline numbers
3. Run the measurement commands above
4. Compare to baseline
5. Don't build anything new until data says otherwise
