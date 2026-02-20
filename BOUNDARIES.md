# Agent Boundaries

This agent operates on Engram only.

## Hard Rules

1. **Never read or write outside `~/Desktop/development/engram/`.**
2. **Never access Monra, Bridge, Alchemy, or any financial services.**
3. **Never access `.env` files, `.ssh/`, or credentials outside this repo.**
4. **Always request human approval before `git push`.**
5. **Never run destructive commands (`rm -rf`, `DROP TABLE`, etc.) without approval.**

## Allowed (Autonomous)

- Run the engram test suite (`pytest tests/`)
- Search past sessions via `engram search`
- Read engram source code, docs, and roadmap
- Draft code changes (stage in working tree, do not commit without review)
- Monitor GitHub issues (read-only)
- Generate daily progress summaries
- Update documentation within this repo

## Requires Approval

- Any file write outside `tests/` and `docs/`
- Any `git commit`, `git push`, or branch creation
- Any external API call
- Installing new dependencies
- Modifying `pyproject.toml`
- Creating new top-level files or directories

## Verification

The agent should periodically confirm it has not accessed any path outside engram/.
If a task requires cross-project access, stop and ask the human.
