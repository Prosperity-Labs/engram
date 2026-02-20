"""Codex adapter — parses ~/.codex/sessions/ JSONL files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import AgentAdapter, EngramSession, Turn, ToolCall


class CodexAdapter(AgentAdapter):
    agent_name = "codex"

    def parse_file(self, filepath: str) -> EngramSession:
        """Parse a Codex JSONL session file.

        Session file format: each line has {timestamp, type, payload}.
        Types: session_meta, response_item, event_msg, turn_context.
        """
        events = []
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        # Extract session ID from session_meta event, or fall back to filename
        session_id = None
        project = None
        for event in events:
            if event.get("type") == "session_meta":
                payload = event.get("payload", {})
                session_id = payload.get("id")
                project = payload.get("cwd", "").split("/")[-1] if payload.get("cwd") else None
                break

        if not session_id:
            # Extract from filename: rollout-2026-02-17T21-19-39-019c2079-....jsonl
            name = Path(filepath).stem
            # Session ID is the UUID part after the date prefix
            parts = name.split("-")
            # Find where UUID starts (4 hex chars after date parts)
            session_id = name

        session = EngramSession(
            session_id=session_id,
            agent="codex",
            project=project,
            filepath=filepath,
            raw_events=events,
        )

        # Track pending function calls to match with outputs
        pending_calls: dict[str, ToolCall] = {}  # call_id -> ToolCall
        last_token_usage = {"in": 0, "out": 0}

        for event in events:
            etype = event.get("type")
            payload = event.get("payload", {})
            ts = event.get("timestamp")

            if etype == "response_item":
                ptype = payload.get("type")

                if ptype == "message":
                    role = payload.get("role", "assistant")
                    content_blocks = payload.get("content", [])
                    text_parts = []
                    for block in content_blocks:
                        if isinstance(block, dict):
                            text = block.get("text", "")
                            if text:
                                text_parts.append(text)
                        elif isinstance(block, str):
                            text_parts.append(block)
                    content = "\n".join(text_parts)
                    if content:
                        turn = Turn(
                            role=role,
                            content=content,
                            timestamp=ts,
                            token_usage_in=last_token_usage["in"],
                            token_usage_out=last_token_usage["out"],
                        )
                        session.turns.append(turn)
                        # Reset token tracking after attributing to a turn
                        last_token_usage = {"in": 0, "out": 0}

                elif ptype == "function_call":
                    name = payload.get("name", "unknown")
                    arguments_str = payload.get("arguments", "{}")
                    call_id = payload.get("call_id")
                    try:
                        arguments = json.loads(arguments_str)
                    except (json.JSONDecodeError, TypeError):
                        arguments = {"raw": arguments_str}

                    # Map Codex tool names to normalized names
                    tool_name = self._normalize_tool_name(name)
                    tc = ToolCall(
                        name=tool_name,
                        input=arguments,
                        tool_use_id=call_id,
                    )
                    if call_id:
                        pending_calls[call_id] = tc

                    # Create a turn for this tool call
                    turn = Turn(
                        role="assistant",
                        content="",
                        tool_calls=[tc],
                        timestamp=ts,
                    )
                    session.turns.append(turn)

                elif ptype == "function_call_output":
                    call_id = payload.get("call_id")
                    output = payload.get("output", "")
                    if call_id and call_id in pending_calls:
                        pending_calls[call_id].output = output[:500] if output else None

            elif etype == "event_msg":
                ptype = payload.get("type")

                if ptype == "token_count":
                    info = payload.get("info", {})
                    usage = info.get("total_token_usage", {})
                    last_token_usage["in"] = (
                        usage.get("input_tokens", 0)
                        + usage.get("cached_input_tokens", 0)
                    )
                    last_token_usage["out"] = usage.get("output_tokens", 0)

                elif ptype == "agent_reasoning":
                    # Store reasoning as a turn (useful for replay/audit)
                    text = payload.get("text", "")
                    if text:
                        turn = Turn(
                            role="assistant",
                            content=f"[reasoning] {text}",
                            timestamp=ts,
                        )
                        session.turns.append(turn)

        # Set session times
        if session.turns:
            session.start_time = session.turns[0].timestamp
            session.end_time = session.turns[-1].timestamp

        return session

    def parse_event(self, event: dict) -> Turn | None:
        """Parse a single Codex event for live indexing."""
        etype = event.get("type")
        payload = event.get("payload", {})
        ts = event.get("timestamp")

        if etype == "response_item" and payload.get("type") == "message":
            role = payload.get("role", "assistant")
            content_blocks = payload.get("content", [])
            text_parts = []
            for block in content_blocks:
                if isinstance(block, dict):
                    text = block.get("text", "")
                    if text:
                        text_parts.append(text)
            content = "\n".join(text_parts)
            if content:
                return Turn(role=role, content=content, timestamp=ts)

        return None

    def discover_sessions(self) -> list[str]:
        """Find all Codex session files at ~/.codex/sessions/.

        Path format: ~/.codex/sessions/YYYY/MM/DD/rollout-<date>-<session-id>.jsonl
        Returns list of absolute paths sorted by mtime descending.
        """
        codex_dir = Path.home() / ".codex" / "sessions"
        if not codex_dir.exists():
            return []
        paths = list(codex_dir.rglob("*.jsonl"))
        # Sort by modification time, newest first
        paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [str(p) for p in paths]

    def guess_project(self, filepath: str) -> str | None:
        """Extract project from session_meta cwd field.

        Must read the file to get this — stored in session_meta payload.
        """
        try:
            with open(filepath) as f:
                for line in f:
                    event = json.loads(line.strip())
                    if event.get("type") == "session_meta":
                        cwd = event.get("payload", {}).get("cwd", "")
                        if cwd:
                            return cwd.split("/")[-1]
                        break
        except (json.JSONDecodeError, FileNotFoundError):
            pass
        return None

    @staticmethod
    def _normalize_tool_name(codex_name: str) -> str:
        """Map Codex tool names to normalized Engram names.

        Codex uses: exec_command, write_file, read_file, etc.
        Engram uses: Bash, Write, Read, etc.
        """
        mapping = {
            "exec_command": "Bash",
            "shell": "Bash",
            "write_file": "Write",
            "read_file": "Read",
            "apply_diff": "Edit",
            "create_file": "Write",
            "delete_file": "Delete",
        }
        return mapping.get(codex_name, codex_name)
