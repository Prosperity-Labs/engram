# Agent Spec: Codex — Artifact Extractor + Sessions List

> **Branch:** `v020-codex`
> **Agent:** Codex
> **Scope:** `engram/recall/artifact_extractor.py` (new) + `engram/sessions.py` (new)

---

## Task 1: Artifact Extractor

**New file:** `engram/recall/artifact_extractor.py`

### Interface contract:

```python
from engram.recall.session_db import SessionDB

class ArtifactExtractor:
    def __init__(self, db: SessionDB):
        self.db = db
        self._init_schema()

    def _init_schema(self):
        """Create artifacts table if it doesn't exist."""

    def extract_session(self, session_id: str) -> list[dict]:
        """Extract artifacts from all messages in a session.

        Returns list of dicts:
        {
            "session_id": str,
            "artifact_type": str,   # file_read, file_write, file_create, command, api_call, error
            "target": str,          # file path, command string, API endpoint
            "tool_name": str,       # original tool name (Read, Edit, Write, Bash, etc.)
            "sequence": int,        # message sequence number
            "context": str | None,  # short context (first 200 chars of surrounding content)
        }
        """

    def extract_all(self) -> dict:
        """Extract artifacts from all sessions.
        Returns: {"sessions_processed": int, "artifacts_extracted": int}
        """

    def get_artifacts(
        self,
        session_id: str | None = None,
        project: str | None = None,
        artifact_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query stored artifacts with optional filters."""

    def summary(self, session_id: str) -> dict:
        """Return artifact summary for a session.
        Returns:
        {
            "files_read": int,
            "files_written": int,
            "files_created": int,
            "commands": int,
            "api_calls": int,
            "errors": int,
            "top_files": list[tuple[str, int]],  # (path, access_count)
            "top_commands": list[tuple[str, int]],
        }
        """
```

### Schema to create (in `_init_schema`):

```sql
CREATE TABLE IF NOT EXISTS artifacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    target        TEXT NOT NULL,
    tool_name     TEXT,
    sequence      INTEGER,
    context       TEXT,
    UNIQUE(session_id, artifact_type, target, sequence)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_session ON artifacts(session_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_type ON artifacts(artifact_type);
CREATE INDEX IF NOT EXISTS idx_artifacts_target ON artifacts(target);
```

### Extraction rules:

| tool_name | artifact_type | target field |
|-----------|--------------|--------------|
| `Read` | `file_read` | `file_path` from content |
| `Glob` | `file_read` | `pattern` from content |
| `Grep` | `file_read` | `pattern` + `path` from content |
| `Edit` | `file_write` | `file_path` from content |
| `Write` | `file_create` | `file_path` from content |
| `Bash` | `command` | `command` from content |
| `mcp_*` | `api_call` | tool name as target |
| Content has "error"/"Error"/"ERROR" + role=assistant | `error` | first 200 chars of content |

### Content parsing:

Messages with `tool_name` have content in TWO possible formats:

**Format 1 — String:** `tool_use:Read(file_path=..., limit=...)`
Parse with regex: `r'tool_use:(\w+)\(([^)]*)\)'`
Extract key=value pairs from params. The `file_path` param (or `command` for Bash) is the target.

**Format 2 — JSON dict:** `{"file_path": "/path/to/file", ...}`
Parse with `json.loads()`. Extract `file_path`, `command`, `pattern`, or `path` key.

### Dependencies:
- Uses `SessionDB` from `engram.recall.session_db`
- Schema gets added to the same database (sessions.db)
- Use `db._connect()` context manager for all DB access

### Verification:

```python
from engram.recall.artifact_extractor import ArtifactExtractor
from engram.recall.session_db import SessionDB

extractor = ArtifactExtractor(SessionDB())
result = extractor.extract_all()
assert result["sessions_processed"] > 0
assert result["artifacts_extracted"] > 0

artifacts = extractor.get_artifacts(artifact_type="file_write", limit=5)
assert all(a["artifact_type"] == "file_write" for a in artifacts)

summary = extractor.summary(artifacts[0]["session_id"])
assert summary["files_written"] > 0
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
    ...
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

**Sort variants:**
- `"recent"` → `ORDER BY s.updated_at DESC`
- `"messages"` → `ORDER BY s.message_count DESC`
- `"tokens"` → `ORDER BY tokens_in DESC`

**Project filter:** Add `AND s.project = ?` when `project` is provided.

### Dependencies:
- Uses `SessionDB` from `engram.recall.session_db`

### Verification:

```python
from engram.sessions import list_sessions, render_sessions
from engram.recall.session_db import SessionDB

sessions = list_sessions(SessionDB(), limit=10)
assert len(sessions) > 0
assert all("session_id" in s for s in sessions)

rendered = render_sessions(sessions)
assert "SESSION" in rendered  # header present
```

---

## Deliverables

When done:
1. Run existing tests: `pytest tests/ -v` — all must pass (no regressions)
2. Run v0.2.0 tests: `pytest tests/test_v020.py -v` — report results
3. `git add engram/recall/artifact_extractor.py engram/sessions.py`
4. `git commit -m 'feat: artifact extractor + sessions list (v0.2.0)'`
5. Do NOT `git push`
