## Improve enrichment brief quality

The current briefs for most projects are too thin.
"explored codebase. 399 messages" is useless to an agent.

Fix generate_slim_brief() in engram/brief.py to ALWAYS include
these sections, even for projects with few sessions:

1. Key Files (top 5 most-read + top 5 most-edited with counts)
2. Co-Change Pairs (files edited together 2+ times)
3. Danger Zones (files with high error:write ratio)
4. Recent Activity (last 3 sessions: date, what was done, outcome)
5. Known Errors (recurring error patterns with which files)
6. Session Stats (total sessions, messages, date range)

If a section has no data, omit it. But never return a one-liner.
Minimum useful brief is 5-10 lines.

Test by running:
  python -c "from engram.brief import generate_slim_brief;
  print(generate_slim_brief('engram'))"

Do this for: engram, monra-core, monra-app, music-nft-platform,
Loopwright, openclaw

Show me the before and after for each project.

### Prerequisites
- Fix `_resolve_project()` in `engram/proxy/enrichment.py` first — it picks `engram` (5 sessions) over the full path (25 sessions, 5,688 msgs). Should prefer the match with most sessions.
- `generate_slim_brief()` takes `(db, project)` — the test command above needs adjusting to pass a SessionDB instance.

### Known Issues
- Key Decisions truncated mid-sentence at 120 chars with no sentence boundary logic
- Project name fragmentation: short names vs full paths vs worktree paths all treated as separate projects
- Brief should aggregate data from all matching project variants
