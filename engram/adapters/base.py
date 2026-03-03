"""Base adapter and normalized session format for Engram."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """A single tool invocation within a turn."""

    name: str
    input: dict[str, Any]
    output: str | None = None
    tool_use_id: str | None = None


@dataclass
class Turn:
    """A single conversational turn."""

    role: str  # "user" | "assistant" | "summary"
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    timestamp: str | None = None
    token_usage_in: int = 0
    token_usage_out: int = 0
    cache_read_tokens: int = 0
    cache_create_tokens: int = 0
    agent_id: str | None = None


@dataclass
class EngramSession:
    """Agent-agnostic normalized session format.

    Every adapter produces this. All downstream code (compression,
    manifest writer, inspector, replay) consumes only this.
    """

    session_id: str
    agent: str  # "claude_code" | "cursor" | "codex"
    project: str | None = None
    filepath: str | None = None
    turns: list[Turn] = field(default_factory=list)
    start_time: str | None = None
    end_time: str | None = None
    raw_events: list[dict] = field(default_factory=list)

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
        """Convert turns to the flat message format SessionDB expects.

        Returns list of dicts with keys:
            role, content, timestamp, tool_name,
            token_usage_in, token_usage_out,
            cache_read_tokens, cache_create_tokens
        """
        messages: list[dict] = []
        for turn in self.turns:
            base = {
                "role": turn.role,
                "timestamp": turn.timestamp,
                "token_usage_in": turn.token_usage_in,
                "token_usage_out": turn.token_usage_out,
                "cache_read_tokens": turn.cache_read_tokens,
                "cache_create_tokens": turn.cache_create_tokens,
                "agent_id": turn.agent_id,
            }
            if not turn.tool_calls:
                messages.append({**base, "content": turn.content, "tool_name": None})
            else:
                # Text content first (if any)
                if turn.content.strip():
                    messages.append({**base, "content": turn.content, "tool_name": None})
                # Each tool call as a separate message row (zero tokens — attributed to first)
                zero_tokens = {
                    "token_usage_in": 0, "token_usage_out": 0,
                    "cache_read_tokens": 0, "cache_create_tokens": 0,
                }
                for tc in turn.tool_calls:
                    input_str = str(tc.input) if tc.input else ""
                    messages.append({
                        "role": turn.role,
                        "content": input_str,
                        "timestamp": turn.timestamp,
                        "tool_name": tc.name,
                        "agent_id": turn.agent_id,
                        **zero_tokens,
                    })
        return messages


class AgentAdapter(ABC):
    """Base class for all agent adapters.

    Each adapter reads one agent's session format and produces
    an EngramSession. Downstream code never sees raw agent data.
    """

    agent_name: str

    @abstractmethod
    def parse_file(self, filepath: str) -> EngramSession:
        """Parse a session file into an EngramSession."""
        ...

    @abstractmethod
    def parse_event(self, event: dict) -> Turn | None:
        """Parse a single event into a Turn (for live indexing).

        Returns None if the event doesn't produce a meaningful turn.
        """
        ...

    @abstractmethod
    def discover_sessions(self) -> list[str]:
        """Return list of session file paths this adapter can find."""
        ...
