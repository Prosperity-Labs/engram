# Agent Spec: Cursor — Stats + Sessions + Export

> **Branch:** `v020-cursor`
> **Agent:** Cursor
> **Scope:** `engram/stats.py` (new) + `engram/sessions.py` (new) + `engram/export.py` (new)

---

## Task 1: Stats Command

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

### Bar rendering helper:

```python
def _bar(ratio: float, width: int = 16) -> str:
    filled = int(ratio * width)
    return "#" * filled + "." * (width - filled)
```

---

## Task 2: Sessions List Command

**New file:** `engram/sessions.py`

### Interface contract:

```python
from engram.recall.session_db import SessionDB

def list_sessions(
    db: SessionDB,
    project: str | None = None,
    min_messages: int = 0,
    sort_by: str = "recent",  # "recent", "messages", "tokens"
    limit: int = 50,
) -> list[dict]:
    """List sessions with metadata.

    Returns list of dicts:
    {
        "session_id": str,
        "project": str,
        "message_count": int,
        "tokens_in": int,
        "tokens_out": int,
        "tool_calls": int,
        "created_at": str | None,
        "updated_at": str | None,
        "file_size_bytes": int,
    }
    """

def render_sessions(sessions: list[dict]) -> str:
    """Render session list as terminal-friendly table.

    Format:
    SESSION       PROJECT          MSGS  TOOLS  TOKENS IN   UPDATED
    46971622...   monra-app       1,040    382    68.3M     2026-02-18 19:30
    d534d0a0...   monra-app         931    341    62.3M     2026-02-18 23:20
    """
```

### SQL query:

```sql
SELECT s.session_id, s.project, s.message_count, s.file_size_bytes,
       s.created_at, s.updated_at,
       COALESCE(SUM(m.token_usage_in), 0) as tokens_in,
       COALESCE(SUM(m.token_usage_out), 0) as tokens_out,
       COUNT(CASE WHEN m.tool_name IS NOT NULL THEN 1 END) as tool_calls
FROM sessions s
LEFT JOIN messages m ON m.session_id = s.session_id
WHERE s.message_count > ?
GROUP BY s.session_id
ORDER BY s.updated_at DESC
LIMIT ?
```

**Sort variants:** `"recent"` -> `ORDER BY s.updated_at DESC`, `"messages"` -> `ORDER BY s.message_count DESC`, `"tokens"` -> `ORDER BY tokens_in DESC`

**Project filter:** Add `AND s.project = ?` when project is provided.

---

## Task 3: Export to JSON/CSV

**New file:** `engram/export.py`

### Interface contract:

```python
from engram.recall.session_db import SessionDB

def export_events(
    db: SessionDB,
    format: str = "json",  # "json" or "csv"
    project: str | None = None,
    session_id: str | None = None,
    output: str | None = None,  # file path; None = stdout
) -> str:
    """Export session events to JSON or CSV.

    JSON format: list of dicts, one per message
    CSV format: header row + data rows

    Columns: session_id, project, sequence, role, tool_name,
             content (truncated to 500 chars), timestamp,
             token_usage_in, token_usage_out

    Returns: the output string (also writes to file if output is set)
    """

def export_sessions(
    db: SessionDB,
    format: str = "json",
    output: str | None = None,
) -> str:
    """Export session metadata to JSON or CSV.

    Columns: session_id, project, message_count, file_size_bytes,
             created_at, updated_at

    Returns: the output string
    """
```

### Implementation notes:

- Use `json.dumps(data, indent=2, default=str)` for JSON
- Use `csv.DictWriter` for CSV with `io.StringIO`
- Truncate content to 500 chars to keep exports manageable
- For filtering: use SQL WHERE clauses, not post-filtering

### SQL for events export:

```sql
SELECT m.session_id, s.project, m.sequence, m.role, m.tool_name,
       SUBSTR(m.content, 1, 500) as content, m.timestamp,
       m.token_usage_in, m.token_usage_out
FROM messages m
LEFT JOIN sessions s ON s.session_id = m.session_id
WHERE 1=1
ORDER BY m.session_id, m.sequence
```

Add `AND s.project = ?` or `AND m.session_id = ?` as needed.

### Verification:

```python
from engram.export import export_events, export_sessions
from engram.recall.session_db import SessionDB
import json, csv, io

db = SessionDB()

# JSON export
result = export_events(db, format="json", project="monra-app")
data = json.loads(result)
assert isinstance(data, list)
assert len(data) > 0
assert "session_id" in data[0]

# CSV export
result = export_events(db, format="csv", project="monra-app")
reader = csv.DictReader(io.StringIO(result))
rows = list(reader)
assert len(rows) > 0
assert "session_id" in rows[0]

# Session metadata export
result = export_sessions(db, format="json")
data = json.loads(result)
assert len(data) > 0
```

---

## Deliverables

When done:
1. Run existing tests: `pytest tests/ -v` — all must pass (no regressions)
2. Run v0.2.0 tests: `pytest tests/test_v020.py -v` — report results
3. `git add engram/stats.py engram/sessions.py engram/export.py`
4. `git commit -m 'feat: stats + sessions + export (v0.2.0)'`
5. Do NOT `git push`
