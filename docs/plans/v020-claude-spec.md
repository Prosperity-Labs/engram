# Agent Spec: Claude — Project Name Cleaner + Stats Command

> **Branch:** `v020-claude`
> **Agent:** Claude Code
> **Scope:** `engram/recall/session_db.py` (modify) + `engram/stats.py` (new)

---

## Task 1: Project Name Cleaner

**Modify:** `engram/recall/session_db.py`

### Add this standalone function (module-level, near `_guess_project`):

```python
def clean_project_name(raw: str) -> str:
    """Clean raw Claude Code project directory names into readable project names.

    Input examples:
        "-home-prosperitylabs-Desktop-development-monra-app" -> "monra-app"
        "-home-prosperitylabs-Desktop-development-monra-app-monra-core" -> "monra-app/monra-core"
        "-home-prosperitylabs-Desktop-development-music-nft-platform" -> "music-nft-platform"
        "-home-prosperitylabs-Desktop-development" -> "development"
        "-home-prosperitylabs--claude-plugins-marketplaces-thedotmack-plugin" -> "thedotmack-plugin"
        "app" -> "app"  # already clean
        "graph" -> "graph"  # already clean

    Rules:
    1. If doesn't start with "-home-" or "-", return as-is (already clean)
    2. Strip the home directory prefix: everything up to and including "development-" or the last known base dir
    3. For paths with TWO directories after development (e.g. monra-app-monra-core), join with "/"
    4. Keep compound names like "music-nft-platform" intact (these are real project names with hyphens)
    """
```

**Heuristic approach for splitting:**
- Known base path markers: `"development"`, `"Desktop"`, `"projects"`, `"plugins"`, `"marketplaces"`
- After stripping prefix up to the last marker: the remainder is the project path
- If a known project directory exists (check filesystem or use heuristics), split there
- Simple heuristic: if the remaining path has a segment that appears in the session database as a separate project, it's a path separator

### Add method to SessionDB class:

```python
def clean_all_project_names(self) -> int:
    """Update all sessions with cleaned project names. Returns count updated."""
    with self._connect() as conn:
        rows = conn.execute("SELECT session_id, project FROM sessions WHERE project IS NOT NULL").fetchall()
        updated = 0
        for row in rows:
            cleaned = clean_project_name(row["project"])
            if cleaned != row["project"]:
                conn.execute("UPDATE sessions SET project = ? WHERE session_id = ?", (cleaned, row["session_id"]))
                updated += 1
    return updated
```

### Wire into existing methods:

1. In `_guess_project()` — apply `clean_project_name()` to the return value
2. In `upsert_session_meta()` — apply `clean_project_name()` to the `project` param before INSERT

### Test assertions:

```python
assert clean_project_name("-home-prosperitylabs-Desktop-development-monra-app") == "monra-app"
assert clean_project_name("-home-prosperitylabs-Desktop-development-monra-app-monra-core") == "monra-app/monra-core"
assert clean_project_name("-home-prosperitylabs-Desktop-development-music-nft-platform") == "music-nft-platform"
assert clean_project_name("-home-prosperitylabs-Desktop-development") == "development"
assert clean_project_name("app") == "app"
assert clean_project_name("graph") == "graph"
assert clean_project_name("") == ""
assert clean_project_name("-home-prosperitylabs--claude-plugins-marketplaces-thedotmack-plugin") == "thedotmack-plugin"
```

---

## Task 2: Stats Command

**New file:** `engram/stats.py`

### Interface contract:

```python
from engram.recall.session_db import SessionDB

def compute_project_stats(db: SessionDB) -> list[dict]:
    """Compute per-project analytics.

    Returns list of dicts, one per project:
    {
        "project": str,
        "sessions": int,
        "messages": int,
        "tokens_in": int,
        "tokens_out": int,
        "tokens_per_message": float,
        "tool_calls": int,
        "error_messages": int,
        "error_rate": float,            # error_messages / messages
        "exploration_ratio": float,     # (Read+Grep+Glob) / total_tool_calls
        "mutation_ratio": float,        # (Edit+Write) / total_tool_calls
        "execution_ratio": float,       # Bash / total_tool_calls
        "top_tools": list[tuple[str, int]],  # top 5 tools by count
    }
    """

def compute_session_stats(db: SessionDB, session_id: str) -> dict:
    """Compute stats for a single session. Same shape as above but for one session."""

def render_project_stats(stats: list[dict]) -> str:
    """Render stats as a terminal-friendly string with bars.

    Format per project:

    monra-app (12 sessions, 145M tokens)
      Messages:    4,200  |  Errors: 15%
      Exploration: 36%  ########........
      Mutation:    22%  #####...........
      Execution:   42%  ##########......
      Top tools: Bash (291), Read (159), Edit (122)
    """
```

### SQL query (copy exactly):

```sql
SELECT s.project,
       COUNT(DISTINCT s.session_id) as sessions,
       SUM(s.message_count) as messages,
       SUM(m.token_usage_in) as tokens_in,
       SUM(m.token_usage_out) as tokens_out,
       COUNT(CASE WHEN m.tool_name IS NOT NULL THEN 1 END) as tool_calls,
       COUNT(CASE WHEN m.content LIKE '%error%' OR m.content LIKE '%Error%' THEN 1 END) as error_messages,
       COUNT(CASE WHEN m.tool_name IN ('Read', 'Grep', 'Glob') THEN 1 END) as exploration,
       COUNT(CASE WHEN m.tool_name IN ('Edit', 'Write') THEN 1 END) as mutation,
       COUNT(CASE WHEN m.tool_name = 'Bash' THEN 1 END) as execution
FROM sessions s
LEFT JOIN messages m ON m.session_id = s.session_id
GROUP BY s.project
ORDER BY SUM(m.token_usage_in) DESC
```

### Top tools per project (secondary query):

```sql
SELECT tool_name, COUNT(*) as cnt
FROM messages
WHERE session_id IN (SELECT session_id FROM sessions WHERE project = ?)
  AND tool_name IS NOT NULL
GROUP BY tool_name
ORDER BY cnt DESC
LIMIT 5
```

### Bar rendering:

Use a simple `_bar(ratio, width=16)` function:
```python
def _bar(ratio: float, width: int = 16) -> str:
    filled = int(ratio * width)
    return "#" * filled + "." * (width - filled)
```

### Dependencies:
- `SessionDB` from `engram.recall.session_db`
- Access DB via `db._connect()` context manager

### Verification:

```python
from engram.stats import compute_project_stats, render_project_stats
from engram.recall.session_db import SessionDB

stats = compute_project_stats(SessionDB())
assert len(stats) > 0
assert all(s["sessions"] > 0 for s in stats)
assert all(0 <= s["error_rate"] <= 1 for s in stats)
assert all(0 <= s["exploration_ratio"] <= 1 for s in stats)

rendered = render_project_stats(stats)
assert "sessions" in rendered.lower()
```

---

## Deliverables

When done:
1. Run existing tests: `pytest tests/ -v` — all must pass (no regressions)
2. Run v0.2.0 tests: `pytest tests/test_v020.py -v` — report results
3. `git add engram/recall/session_db.py engram/stats.py`
4. `git commit -m 'feat: project name cleaner + stats command (v0.2.0)'`
5. Do NOT `git push`
