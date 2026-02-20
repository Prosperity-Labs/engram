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
