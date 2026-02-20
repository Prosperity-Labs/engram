# Day 1 Delegation Plan — AgentAdapter + ClaudeCodeAdapter

**Branch:** `day1/agent-adapter`
**Goal:** Define `EngramSession` + `AgentAdapter` base class, refactor JSONL parser into `ClaudeCodeAdapter`, fix PATH.

---

## Task A — Codex: EngramSession dataclass + AgentAdapter base class

**Create file:** `engram/adapters/__init__.py` (empty)
**Create file:** `engram/adapters/base.py`

```python
"""Base adapter and normalized session format for Engram."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """A single tool invocation within a turn."""
    name: str                    # e.g. "Read", "Edit", "Bash", "mcp__postgres__run_dql_query"
    input: dict[str, Any]        # tool input parameters
    output: str | None = None    # tool result (truncated to 500 chars for storage)
    tool_use_id: str | None = None


@dataclass
class Turn:
    """A single conversational turn (one user or assistant message)."""
    role: str                    # "user" | "assistant" | "summary"
    content: str                 # text content
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)  # raw tool_result blocks
    timestamp: str | None = None
    token_usage_in: int = 0
    token_usage_out: int = 0


@dataclass
class EngramSession:
    """Agent-agnostic normalized session format.

    Every adapter produces this. All downstream code (compression,
    manifest writer, inspector, replay) consumes only this.
    """
    session_id: str
    agent: str                   # "claude_code" | "cursor" | "codex"
    project: str | None = None
    filepath: str | None = None  # original source file path
    turns: list[Turn] = field(default_factory=list)
    start_time: str | None = None
    end_time: str | None = None
    raw_events: list[dict] = field(default_factory=list)  # original unparsed events

    @property
    def message_count(self) -> int:
        return len(self.turns)

    @property
    def total_tokens_in(self) -> int:
        return sum(t.token_usage_in for t in self.turns)

    @property
    def total_tokens_out(self) -> int:
        return sum(t.token_usage_out for t in self.turns)

    def tool_call_count(self) -> int:
        return sum(len(t.tool_calls) for t in self.turns)

    def to_message_dicts(self) -> list[dict]:
        """Convert turns back to the flat message format SessionDB expects.

        This is the bridge between the new adapter output and the existing
        SessionDB.insert_messages() / index_session() flow.

        Returns list of dicts with keys:
            role, content, timestamp, tool_name, token_usage_in, token_usage_out
        """
        messages = []
        for turn in self.turns:
            if not turn.tool_calls:
                messages.append({
                    "role": turn.role,
                    "content": turn.content,
                    "timestamp": turn.timestamp,
                    "tool_name": None,
                    "token_usage_in": turn.token_usage_in,
                    "token_usage_out": turn.token_usage_out,
                })
            else:
                # First: the text content (if any)
                if turn.content.strip():
                    messages.append({
                        "role": turn.role,
                        "content": turn.content,
                        "timestamp": turn.timestamp,
                        "tool_name": None,
                        "token_usage_in": turn.token_usage_in,
                        "token_usage_out": turn.token_usage_out,
                    })
                # Then each tool call as a separate message row
                for tc in turn.tool_calls:
                    input_str = str(tc.input) if tc.input else ""
                    messages.append({
                        "role": turn.role,
                        "content": input_str,
                        "timestamp": turn.timestamp,
                        "tool_name": tc.name,
                        "token_usage_in": 0,
                        "token_usage_out": 0,
                    })
        return messages


class AgentAdapter(ABC):
    """Base class for all agent adapters.

    Each adapter knows how to read one agent's session format and produce
    an EngramSession. Downstream code never sees raw agent data.
    """

    agent_name: str  # "claude_code", "cursor", "codex"

    @abstractmethod
    def parse_file(self, filepath: str) -> EngramSession:
        """Parse a session file into an EngramSession."""
        ...

    @abstractmethod
    def parse_event(self, event: dict) -> Turn | None:
        """Parse a single event/message into a Turn (for live indexing).

        Returns None if the event doesn't produce a meaningful turn.
        """
        ...

    @abstractmethod
    def discover_sessions(self) -> list[str]:
        """Return list of session file paths this adapter can find."""
        ...
```

**Verification:**
```bash
cd /home/prosperitylabs/Desktop/development/engram
python3 -c "
from engram.adapters.base import EngramSession, Turn, ToolCall, AgentAdapter
s = EngramSession(session_id='test', agent='claude_code')
t = Turn(role='user', content='hello')
tc = ToolCall(name='Read', input={'file_path': '/foo'})
t.tool_calls.append(tc)
s.turns.append(t)
assert s.message_count == 1
assert s.tool_call_count() == 1
msgs = s.to_message_dicts()
assert len(msgs) == 2  # text + tool call
assert msgs[1]['tool_name'] == 'Read'
print('OK: EngramSession + AgentAdapter base class works')
"
```

---

## Task B — Cursor: ClaudeCodeAdapter (refactor existing JSONL parser)

**Create file:** `engram/adapters/claude_code.py`

Refactor the existing JSONL parsing logic from `engram/recall/session_db.py` (lines 311-415, the `_extract_messages` method) and `engram/recall/live_indexer.py` (the `_parse_new_lines` method) into a proper adapter.

**Important:** Read these existing files first:
- `/home/prosperitylabs/Desktop/development/engram/engram/recall/session_db.py` — the `_extract_messages` method (line 311)
- `/home/prosperitylabs/Desktop/development/engram/engram/recall/live_indexer.py` — the `_parse_new_lines` method (line 106)
- `/home/prosperitylabs/Desktop/development/engram/engram/adapters/base.py` — the base classes (created by Task A)

**Interface:**
```python
"""Claude Code adapter — parses ~/.claude/ JSONL session files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import AgentAdapter, EngramSession, Turn, ToolCall


class ClaudeCodeAdapter(AgentAdapter):
    agent_name = "claude_code"

    def parse_file(self, filepath: str) -> EngramSession:
        """Parse an entire Claude Code JSONL session file.

        Reads the file line by line, parses each JSON entry,
        and produces an EngramSession with proper Turn objects.

        Each JSONL entry has: {"type": "user"|"assistant"|"summary", "timestamp": ..., "message": {...}}

        For assistant entries, message.content is a list of blocks:
        - {"type": "text", "text": "..."} → text content
        - {"type": "tool_use", "name": "Read", "input": {...}} → tool call
        - {"type": "thinking", "thinking": "..."} → thinking block (store as content)

        For user entries, message.content can be:
        - A string
        - A list of blocks: {"type": "text", "text": "..."} or {"type": "tool_result", "content": ...}

        Token usage comes from message.usage: {input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens}
        Total input = input_tokens + cache_read_input_tokens + cache_creation_input_tokens
        """
        ...

    def parse_event(self, event: dict) -> Turn | None:
        """Parse a single JSONL event dict into a Turn."""
        ...

    def discover_sessions(self) -> list[str]:
        """Find all Claude Code JSONL session files.

        Scans ~/.claude/projects/*/*.jsonl
        Returns list of absolute file paths sorted by size descending.
        """
        ...

    def guess_project(self, filepath: str) -> str | None:
        """Extract project name from Claude Code session path.

        Path format: ~/.claude/projects/<project-dir>/<session-id>.jsonl
        Returns the <project-dir> segment.
        """
        ...
```

**Key rules for parsing:**
1. Each assistant JSONL entry may contain multiple content blocks — create ONE Turn per entry, with tool_calls populated from tool_use blocks and text concatenated from text blocks
2. User entries: concatenate all text blocks and tool_result content into one Turn
3. Summary entries: extract content (may be in entry.summary, message.summary, or message.content) into one Turn with role="summary"
4. Token usage: total_in = input_tokens + cache_read_input_tokens + cache_creation_input_tokens. Attribute to the Turn, not each block.
5. Tool calls: extract name + input dict into ToolCall objects on the Turn

**Also modify:** `engram/recall/session_db.py`
- Add a method `index_from_session(self, session: EngramSession) -> dict` that takes an EngramSession and indexes it (using `session.to_message_dicts()` to get the flat format)
- Keep the existing `index_session(filepath)` method working (it should internally create a ClaudeCodeAdapter, call parse_file, then call index_from_session)
- Keep `_extract_messages` as-is for backward compatibility but have `index_session` use the adapter path

**Also modify:** `engram/cli.py`
- In `cmd_install`, use `ClaudeCodeAdapter.discover_sessions()` instead of hardcoded glob
- Still use `db.index_session(filepath)` for actual indexing (it now uses the adapter internally)

**Verification:**
```bash
cd /home/prosperitylabs/Desktop/development/engram
python3 -c "
from engram.adapters.claude_code import ClaudeCodeAdapter
adapter = ClaudeCodeAdapter()

# Test discovery
sessions = adapter.discover_sessions()
print(f'Found {len(sessions)} sessions')
assert len(sessions) > 0

# Test parsing
session = adapter.parse_file(sessions[0])
print(f'Session {session.session_id}: {session.message_count} turns, {session.tool_call_count()} tool calls')
assert session.agent == 'claude_code'
assert session.message_count > 0

# Test backward compat
from engram.recall.session_db import SessionDB
db = SessionDB()
# This should still work exactly as before
print('OK: ClaudeCodeAdapter works')
"
```

---

## Task C — Opus (me): CLI PATH fix + integration wiring

After Tasks A and B are done, I will:
1. Fix PATH so `engram` works from any directory (verify pyproject.toml entry point)
2. Wire the adapter into `cmd_install`
3. Test end-to-end: `engram install`, `engram search`, `engram monitor`
4. Commit and push

---

## Execution

```
Task A (Codex) → EngramSession + AgentAdapter base     ~5 min
Task B (Cursor) → ClaudeCodeAdapter + session_db bridge ~10 min
Task C (Opus)  → Integration + PATH fix                 ~5 min, after A+B
```

Tasks A and B can run in parallel. Task C depends on both.
