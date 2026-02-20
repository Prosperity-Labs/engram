# Day 3 — CodexAdapter

**Branch:** `day3/codex-adapter`
**Goal:** Parse Codex sessions from `~/.codex/sessions/`. Codex sessions appear in Engram alongside Claude Code and Cursor.

---

## Context

Codex CLI stores sessions as JSONL files at `~/.codex/sessions/YYYY/MM/DD/rollout-<date>-<session-id>.jsonl`.
There's also `~/.codex/history.jsonl` with simple `{session_id, ts, text}` entries (user messages only).

### Real Codex JSONL format (from actual session files)

Each line is a JSON object with `timestamp`, `type`, and `payload` fields:

```jsonl
{"timestamp":"2026-02-17T21:19:39Z","type":"session_meta","payload":{"id":"019c2079-...","cwd":"/home/user/project","originator":"codex_cli_rs","cli_version":"0.102.0","source":"cli","model_provider":"openai"}}
{"timestamp":"2026-02-17T21:19:39Z","type":"event_msg","payload":{"type":"task_started","turn_id":"turn-001","model_context_window":258400}}
{"timestamp":"2026-02-17T21:19:39Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"Fix the deploy script"}]}}
{"timestamp":"2026-02-17T21:19:42Z","type":"event_msg","payload":{"type":"agent_reasoning","text":"Looking at deploy configuration"}}
{"timestamp":"2026-02-17T21:19:42Z","type":"response_item","payload":{"type":"function_call","name":"exec_command","arguments":"{\"cmd\":\"cat deploy.sh\"}","call_id":"call_001"}}
{"timestamp":"2026-02-17T21:19:43Z","type":"response_item","payload":{"type":"function_call_output","call_id":"call_001","output":"#!/bin/bash\necho 'deploying...'"}}
{"timestamp":"2026-02-17T21:19:50Z","type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"input_tokens":5000,"cached_input_tokens":2000,"output_tokens":300,"reasoning_output_tokens":50,"total_tokens":5300}}}}
{"timestamp":"2026-02-17T21:19:55Z","type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Fixed the deploy script."}]}}
```

### Entry types

| `type` | `payload.type` | What it is |
|---|---|---|
| `session_meta` | — | Session metadata: id, cwd, cli_version |
| `response_item` | `message` | User or assistant message (role + content array) |
| `response_item` | `function_call` | Tool call: name, arguments (JSON string), call_id |
| `response_item` | `function_call_output` | Tool result: call_id, output |
| `event_msg` | `task_started` | Turn started |
| `event_msg` | `agent_reasoning` | Agent thinking (internal reasoning) |
| `event_msg` | `token_count` | Cumulative token usage |
| `turn_context` | — | Context/history for a turn |

---

## Task A — Create `engram/adapters/codex.py`

```python
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
```

---

## Task B — Create tests

Create `tests/test_codex_adapter.py`:

```python
"""Tests for the Codex adapter."""

from engram.adapters.codex import CodexAdapter


class TestCodexAdapterParsing:
    def test_parse_fixture(self, codex_session):
        """Test parsing the Codex fixture from conftest.py."""
        adapter = CodexAdapter()
        session = adapter.parse_file(str(codex_session))

        assert session.session_id == "019c-test-codex-session"
        assert session.agent == "codex"
        assert session.message_count > 0

    def test_user_message_extracted(self, codex_session):
        adapter = CodexAdapter()
        session = adapter.parse_file(str(codex_session))

        user_turns = [t for t in session.turns if t.role == "user"]
        assert len(user_turns) >= 1
        assert "deploy" in user_turns[0].content.lower()

    def test_function_calls_extracted(self, codex_session):
        adapter = CodexAdapter()
        session = adapter.parse_file(str(codex_session))

        tool_turns = [t for t in session.turns if t.tool_calls]
        assert len(tool_turns) >= 1
        # exec_command should be normalized to Bash
        tool_names = [tc.name for t in tool_turns for tc in t.tool_calls]
        assert "Bash" in tool_names

    def test_function_output_matched(self, codex_session):
        adapter = CodexAdapter()
        session = adapter.parse_file(str(codex_session))

        tool_turns = [t for t in session.turns if t.tool_calls]
        # The exec_command call should have output matched via call_id
        bash_calls = [tc for t in tool_turns for tc in t.tool_calls if tc.name == "Bash"]
        assert len(bash_calls) >= 1
        assert bash_calls[0].output is not None

    def test_token_usage(self, codex_session):
        adapter = CodexAdapter()
        session = adapter.parse_file(str(codex_session))

        # Token usage from event_msg token_count: 5000 input + 2000 cached = 7000
        assert session.total_tokens_in > 0

    def test_reasoning_captured(self, codex_session):
        adapter = CodexAdapter()
        session = adapter.parse_file(str(codex_session))

        reasoning = [t for t in session.turns if "[reasoning]" in t.content]
        assert len(reasoning) >= 1

    def test_normalize_tool_names(self):
        assert CodexAdapter._normalize_tool_name("exec_command") == "Bash"
        assert CodexAdapter._normalize_tool_name("write_file") == "Write"
        assert CodexAdapter._normalize_tool_name("read_file") == "Read"
        assert CodexAdapter._normalize_tool_name("unknown_tool") == "unknown_tool"

    def test_discover_returns_list(self):
        adapter = CodexAdapter()
        sessions = adapter.discover_sessions()
        assert isinstance(sessions, list)
        # We know there are 5 Codex sessions on this machine
        # But don't hard-assert count in case machine state changes


class TestCodexAdapterProject:
    def test_guess_project(self, codex_session):
        adapter = CodexAdapter()
        project = adapter.guess_project(str(codex_session))
        assert project == "project"  # from fixture cwd: /home/user/project


class TestCodexAdapterIndexing:
    def test_index_via_session(self, tmp_db, codex_session):
        """Test indexing a Codex session through the adapter."""
        adapter = CodexAdapter()
        session = adapter.parse_file(str(codex_session))
        result = tmp_db.index_from_session(session)
        assert result["messages_indexed"] > 0
        assert tmp_db.is_indexed(session.session_id)
```

The `codex_session` fixture already exists in `tests/conftest.py` from Day 1.

---

## Task C — Update CLI for multi-agent discovery

In `engram/cli.py`, update `cmd_install` to discover from all available adapters:

```python
# In cmd_install:
from .adapters.claude_code import ClaudeCodeAdapter
from .adapters.codex import CodexAdapter

claude_adapter = ClaudeCodeAdapter()
codex_adapter = CodexAdapter()

all_sessions = []
for path in claude_adapter.discover_sessions():
    all_sessions.append(("claude_code", path))
for path in codex_adapter.discover_sessions():
    all_sessions.append(("codex", path))

# Try Cursor too if available
try:
    from .adapters.cursor import CursorAdapter
    cursor_adapter = CursorAdapter()
    for path in cursor_adapter.discover_sessions():
        all_sessions.append(("cursor", path))
except ImportError:
    pass
```

---

## Verification

```bash
cd /home/prosperitylabs/Desktop/development/engram
source venv/bin/activate

# All tests pass (including new Codex tests)
pytest tests/ -v

# Can discover real Codex sessions
python3 -c "
from engram.adapters.codex import CodexAdapter
adapter = CodexAdapter()
sessions = adapter.discover_sessions()
print(f'Found {len(sessions)} Codex sessions')
if sessions:
    s = adapter.parse_file(sessions[0])
    print(f'Session {s.session_id}: {s.message_count} turns, {s.tool_call_count()} tool calls')
"

# Can parse real Codex session
python3 -c "
from engram.adapters.codex import CodexAdapter
adapter = CodexAdapter()
sessions = adapter.discover_sessions()
for path in sessions:
    s = adapter.parse_file(path)
    print(f'{s.session_id}: {s.message_count} turns, project={s.project}')
"
```
