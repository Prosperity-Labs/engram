# Day 2 — CursorAdapter

**Branch:** `day2/cursor-adapter`
**Goal:** Cursor sessions flow into Engram via hooks. `engram inspect-list` shows them alongside Claude Code sessions.

---

## Context

Cursor doesn't persist session transcripts to disk like Claude Code or Codex do. Instead, Cursor offers a `hooks.json` file at `~/.cursor/hooks.json` that fires shell commands on events:

- `stop` — fires when a Cursor agent session ends
- `afterFileEdit` — fires after each file edit with the diff
- `beforeShellExecution` — fires before terminal commands run
- `afterMCPExecution` — fires after MCP tool calls

The hook receives event data on **stdin** as JSON. Our strategy: capture the `stop` event to create a session record, and optionally `afterFileEdit` for real-time artifact tracking (most precise file tracking of any agent).

### Existing hooks.json

There are already hooks configured at `~/.cursor/hooks.json`. We must **append** to the existing arrays, not replace them.

---

## Task A — Create `engram/adapters/cursor.py`

```python
"""Cursor adapter — captures sessions via hooks.json events."""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import AgentAdapter, EngramSession, Turn, ToolCall


class CursorAdapter(AgentAdapter):
    agent_name = "cursor"

    # Cursor doesn't have discoverable session files like Claude Code.
    # Sessions are created on-the-fly from hook events.

    def parse_file(self, filepath: str) -> EngramSession:
        """Parse a Cursor session capture file (created by our hook).

        Format: JSONL file where each line is a hook event we captured.
        """
        events = []
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))

        session_id = Path(filepath).stem
        session = EngramSession(
            session_id=session_id,
            agent="cursor",
            filepath=filepath,
            raw_events=events,
        )

        for event in events:
            turn = self.parse_event(event)
            if turn:
                session.turns.append(turn)

        if session.turns:
            session.start_time = session.turns[0].timestamp
            session.end_time = session.turns[-1].timestamp

        return session

    def parse_event(self, event: dict) -> Turn | None:
        """Parse a single Cursor hook event into a Turn.

        Hook events we handle:
        - stop: session ended, contains conversation summary
        - afterFileEdit: file was edited, contains diff
        - afterShellExecution: command was run
        """
        hook_type = event.get("hook_type", event.get("type", ""))
        ts = event.get("timestamp", datetime.now(timezone.utc).isoformat())

        if hook_type == "stop":
            # Session end event — extract any summary/conversation data
            content = event.get("conversation", event.get("summary", "Session ended"))
            return Turn(role="summary", content=str(content), timestamp=ts)

        elif hook_type == "afterFileEdit":
            # File edit event — track as assistant turn with tool call
            file_path = event.get("file_path", event.get("path", "unknown"))
            diff = event.get("diff", "")
            return Turn(
                role="assistant",
                content=f"Edited {file_path}",
                tool_calls=[
                    ToolCall(
                        name="Edit",
                        input={"file_path": file_path},
                        output=diff[:500] if diff else None,
                    )
                ],
                timestamp=ts,
            )

        elif hook_type == "afterShellExecution":
            command = event.get("command", "")
            output = event.get("output", "")
            return Turn(
                role="assistant",
                content=f"Ran: {command}",
                tool_calls=[
                    ToolCall(
                        name="Bash",
                        input={"command": command},
                        output=output[:500] if output else None,
                    )
                ],
                timestamp=ts,
            )

        return None

    def discover_sessions(self) -> list[str]:
        """Find Cursor session capture files.

        Our hook writes to ~/.engram/cursor/<session-id>.jsonl
        """
        capture_dir = Path.home() / ".engram" / "cursor"
        if not capture_dir.exists():
            return []
        return sorted(
            [str(p) for p in capture_dir.glob("*.jsonl")],
            key=lambda p: Path(p).stat().st_size,
            reverse=True,
        )

    @staticmethod
    def hook_capture_dir() -> Path:
        """Directory where our hook script writes captured events."""
        d = Path.home() / ".engram" / "cursor"
        d.mkdir(parents=True, exist_ok=True)
        return d
```

---

## Task B — Create `engram/hooks/cursor_hook.py`

This is the script that Cursor's hooks.json will invoke. It reads event data from stdin and appends it to a session capture file.

```python
#!/usr/bin/env python3
"""Cursor hook script — captures events into Engram session files.

Invoked by Cursor via ~/.cursor/hooks.json. Reads JSON from stdin.
Appends each event to ~/.engram/cursor/<session-id>.jsonl.

Usage in hooks.json:
  "stop": [{"command": "python3 /path/to/engram/hooks/cursor_hook.py stop"}]
  "afterFileEdit": [{"command": "python3 /path/to/engram/hooks/cursor_hook.py afterFileEdit"}]
"""

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


def main():
    hook_type = sys.argv[1] if len(sys.argv) > 1 else "unknown"

    # Read event data from stdin
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, Exception):
        event = {}

    # Add our metadata
    event["hook_type"] = hook_type
    event["timestamp"] = datetime.now(timezone.utc).isoformat()

    # Determine session ID
    # Cursor may provide a session/conversation ID in the event data.
    # If not, we group by date + workspace.
    session_id = (
        event.get("session_id")
        or event.get("conversation_id")
        or f"cursor-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}"
    )

    # Write to capture file
    capture_dir = Path.home() / ".engram" / "cursor"
    capture_dir.mkdir(parents=True, exist_ok=True)
    capture_file = capture_dir / f"{session_id}.jsonl"

    with open(capture_file, "a") as f:
        f.write(json.dumps(event) + "\n")

    # On "stop" event, also trigger indexing
    if hook_type == "stop":
        try:
            from engram.recall.session_db import SessionDB
            db = SessionDB()
            db.index_session(capture_file)
        except Exception:
            pass  # Don't block Cursor if indexing fails


if __name__ == "__main__":
    main()
```

---

## Task C — Wire into Cursor's hooks.json

**Read first:** `~/.cursor/hooks.json` to see existing hooks.

Add entries for `stop` and `afterFileEdit` hooks. Append to existing arrays — do not replace other hooks.

The command should be:
```json
{
  "command": "python3 /home/prosperitylabs/Desktop/development/engram/engram/hooks/cursor_hook.py <hook_type>"
}
```

---

## Task D — Create tests

Create `tests/test_cursor_adapter.py`:

```python
"""Tests for the Cursor adapter."""

from engram.adapters.cursor import CursorAdapter


class TestCursorAdapterParsing:
    def test_parse_file_edit_event(self):
        adapter = CursorAdapter()
        turn = adapter.parse_event({
            "hook_type": "afterFileEdit",
            "file_path": "/src/app.ts",
            "diff": "+const x = 1;",
            "timestamp": "2026-02-21T10:00:00Z",
        })
        assert turn is not None
        assert turn.role == "assistant"
        assert len(turn.tool_calls) == 1
        assert turn.tool_calls[0].name == "Edit"

    def test_parse_stop_event(self):
        adapter = CursorAdapter()
        turn = adapter.parse_event({
            "hook_type": "stop",
            "summary": "Fixed auth flow",
            "timestamp": "2026-02-21T10:05:00Z",
        })
        assert turn is not None
        assert turn.role == "summary"
        assert "auth" in turn.content.lower()

    def test_parse_shell_event(self):
        adapter = CursorAdapter()
        turn = adapter.parse_event({
            "hook_type": "afterShellExecution",
            "command": "npm test",
            "output": "3 passed",
            "timestamp": "2026-02-21T10:02:00Z",
        })
        assert turn is not None
        assert turn.tool_calls[0].name == "Bash"

    def test_discover_returns_list(self):
        adapter = CursorAdapter()
        sessions = adapter.discover_sessions()
        assert isinstance(sessions, list)
```

---

## Task E — Update `engram/cli.py`

In `cmd_install`, add Cursor discovery alongside Claude Code:

```python
from .adapters.cursor import CursorAdapter
cursor_adapter = CursorAdapter()
cursor_sessions = cursor_adapter.discover_sessions()
# Index cursor sessions same way as Claude Code sessions
```

---

## Verification

```bash
cd /home/prosperitylabs/Desktop/development/engram
source venv/bin/activate

# Tests pass
pytest tests/test_cursor_adapter.py -v

# Adapter imports cleanly
python3 -c "from engram.adapters.cursor import CursorAdapter; print('OK')"

# Hook script runs without error
echo '{"file_path": "/test.ts", "diff": "+line"}' | python3 engram/hooks/cursor_hook.py afterFileEdit
ls ~/.engram/cursor/  # Should have a .jsonl file
```
