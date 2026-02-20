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
