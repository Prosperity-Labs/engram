# Codex/Cursor Task: Implement Artifact Trail

## Context

We've completed Phase 1 research into Claude Code JSONL session files. Full findings are in `docs/plans/artifact-trail-plan.md`. The implementation plan is in `docs/plans/artifact-trail-plan.md` (Phase 2 and Phase 3 sections).

## What to build

### 1. Create `engram/artifact_trail.py`

Parse Claude Code JSONL session files and extract a timeline of tool calls (file reads, writes, edits, bash commands).

**Data source:** Raw JSONL files at `~/.claude/projects/*/` — one JSON object per line.

**JSONL structure (critical — discovered from real data):**

Each line has a wrapper with `type`, `timestamp`, `uuid`, `sessionId`, and a `message` object containing a `content` array of blocks.

- `type=assistant` entries contain `tool_use` blocks in `message.content`:
  ```json
  {"type": "tool_use", "id": "toolu_xxx", "name": "Write", "input": {"file_path": "...", "content": "..."}}
  {"type": "tool_use", "id": "toolu_xxx", "name": "Edit", "input": {"file_path": "...", "old_string": "...", "new_string": "...", "replace_all": false}}
  {"type": "tool_use", "id": "toolu_xxx", "name": "Bash", "input": {"command": "...", "description": "..."}}
  {"type": "tool_use", "id": "toolu_xxx", "name": "Read", "input": {"file_path": "..."}}
  ```

- `type=user` entries contain `tool_result` blocks in `message.content`:
  ```json
  {"type": "tool_result", "tool_use_id": "toolu_xxx", "content": "...", "is_error": true/false}
  ```
  - Bash errors have content like: `"Exit code 2\n<stderr output>"`
  - Bash success has stdout in content
  - Write result: `"File created successfully at: /path"`
  - Edit result: `"The file /path has been updated successfully."`

**Implementation:**

```python
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

@dataclass
class ArtifactEvent:
    sequence: int
    timestamp: datetime
    tool_type: str            # WRITE, EDIT, READ, BASH, GLOB, GREP
    file_path: Optional[str]
    old_content: Optional[str] = None   # Edit old_string
    new_content: Optional[str] = None   # Edit new_string / Write full content
    command: Optional[str] = None       # Bash command
    exit_code: Optional[int] = None     # Parsed from "Exit code N"
    stdout: Optional[str] = None        # Bash result output
    description: Optional[str] = None   # Bash description field
    is_error: bool = False
    tool_use_id: str = ""

# Key functions to implement:

def parse_session_trail(jsonl_path: Path) -> list[ArtifactEvent]:
    """Parse a JSONL session file and return ordered list of ArtifactEvents."""
    # 1. Read line by line
    # 2. For type=assistant: extract tool_use blocks from message.content list
    # 3. For type=user: extract tool_result blocks, match via tool_use_id
    # 4. Build ArtifactEvent for each tool_use, enriched with its tool_result
    # 5. Sort by sequence (line order)
    # 6. Parse bash exit codes: re.match(r"Exit code (\d+)", content)
    pass

def find_session_jsonl(session_id: str) -> Optional[Path]:
    """Find the JSONL file for a session ID by searching ~/.claude/projects/."""
    # Search recursively for <session_id>.jsonl
    # Also check <session_id>/ directory pattern (newer format)
    pass

def format_trail(events: list[ArtifactEvent]) -> str:
    """Format events as readable timeline string."""
    # Calculate relative timestamps from first event
    # Format like:
    #   #001 [00:30] READ   validators.ts
    #   #002 [01:20] EDIT   validators.ts  (+6/-4 lines)
    #   #003 [02:10] BASH   npm test       → exit 0
    pass
```

### 2. Modify `engram/cli.py` — Add `trail` subcommand

Look at existing CLI patterns in `engram/cli.py`. It uses `click`. Add:

```python
@cli.command()
@click.argument("session_id")
def trail(session_id: str):
    """Show artifact trail for a session."""
    from engram.artifact_trail import parse_session_trail, find_session_jsonl, format_trail

    jsonl_path = find_session_jsonl(session_id)
    if not jsonl_path:
        click.echo(f"Session {session_id} not found", err=True)
        raise SystemExit(1)

    events = parse_session_trail(jsonl_path)
    click.echo(format_trail(events))
```

### 3. Create `tests/test_artifact_trail.py`

Follow patterns from existing tests in `tests/`. Use pytest with tmp_path fixtures.

Test cases:
1. Parse synthetic JSONL with Write tool_use + tool_result → correct ArtifactEvent
2. Parse synthetic JSONL with Edit tool_use → old_content/new_content populated
3. Parse synthetic JSONL with Bash tool_use → command, exit_code, stdout parsed
4. Parse synthetic JSONL with Read tool_use → file_path captured
5. Test exit code regex parsing: `"Exit code 1\nerror msg"` → exit_code=1, is_error=True
6. Test tool_use → tool_result ID matching
7. Test format_trail output format

Create fixture JSONL data as test constants — each line is a valid JSON object matching the real structure documented above.

## Constraints
- Python 3.10+ (use `from __future__ import annotations`)
- Follow existing code style in `engram/` package
- No new dependencies — only stdlib (json, re, dataclasses, pathlib, datetime)
- Don't modify `session_db.py` or any existing files except `cli.py`
- Don't index artifact events into SQLite — just parse on-demand from JSONL

## Verification
```bash
pytest tests/test_artifact_trail.py -v
engram trail <any-session-id-from-your-machine>
```
