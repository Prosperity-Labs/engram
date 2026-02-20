"""Claude Code adapter — parses ~/.claude/ JSONL session files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import AgentAdapter, EngramSession, Turn, ToolCall


class ClaudeCodeAdapter(AgentAdapter):
    agent_name = "claude_code"

    def parse_file(self, filepath: str) -> EngramSession:
        """Parse an entire Claude Code JSONL session file."""
        path = Path(filepath)
        session_id = path.stem
        project = self.guess_project(filepath)

        turns: list[Turn] = []
        raw_events: list[dict] = []

        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                raw_events.append(entry)
                turn = self.parse_event(entry)
                if turn is not None:
                    turns.append(turn)

        timestamps = [t.timestamp for t in turns if t.timestamp]
        start_time = min(timestamps) if timestamps else None
        end_time = max(timestamps) if timestamps else None

        return EngramSession(
            session_id=session_id,
            agent=self.agent_name,
            project=project,
            filepath=str(path),
            turns=turns,
            start_time=start_time,
            end_time=end_time,
            raw_events=raw_events,
        )

    def parse_event(self, event: dict) -> Turn | None:
        """Parse a single JSONL event dict into a Turn."""
        entry_type = event.get("type")
        ts = event.get("timestamp")
        message = event.get("message") or {}
        usage = message.get("usage") or {}

        # Granular token breakdown
        input_tokens = int(usage.get("input_tokens") or 0)
        cache_read = int(usage.get("cache_read_input_tokens") or 0)
        cache_create = int(usage.get("cache_creation_input_tokens") or 0)
        tokens_out = int(usage.get("output_tokens") or 0)

        # token_usage_in = only the non-cached input tokens (for accurate cost)
        tokens_in = input_tokens

        token_kwargs = {
            "token_usage_in": tokens_in,
            "token_usage_out": tokens_out,
            "cache_read_tokens": cache_read,
            "cache_create_tokens": cache_create,
        }

        if entry_type == "user":
            return self._parse_user(message, ts)

        if entry_type == "assistant":
            return self._parse_assistant(message, ts, **token_kwargs)

        if entry_type == "summary":
            return self._parse_summary(event, message, ts, **token_kwargs)

        return None

    def discover_sessions(self) -> list[str]:
        """Find all Claude Code JSONL session files."""
        base = Path.home() / ".claude" / "projects"
        if not base.exists():
            return []
        sessions = sorted(
            base.glob("*/*.jsonl"),
            key=lambda p: p.stat().st_size,
            reverse=True,
        )
        return [str(p) for p in sessions]

    def guess_project(self, filepath: str) -> str | None:
        """Extract project name from Claude Code session path."""
        parts = Path(filepath).parts
        try:
            idx = parts.index("projects")
            if idx + 1 < len(parts) - 1:
                return parts[idx + 1]
        except ValueError:
            pass
        return None

    # ------------------------------------------------------------------
    # Internal parsers
    # ------------------------------------------------------------------

    def _parse_user(self, message: dict, ts: str | None) -> Turn:
        content_blocks = message.get("content", [])
        text = _collect_text(content_blocks)
        tool_results: list[dict] = []

        if isinstance(content_blocks, list):
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tool_results.append(block)

        return Turn(
            role="user",
            content=text,
            tool_results=tool_results,
            timestamp=ts,
        )

    def _parse_assistant(
        self, message: dict, ts: str | None, *,
        token_usage_in: int = 0, token_usage_out: int = 0,
        cache_read_tokens: int = 0, cache_create_tokens: int = 0,
    ) -> Turn | None:
        content_blocks = message.get("content", [])
        if isinstance(content_blocks, str):
            return Turn(
                role="assistant",
                content=content_blocks,
                timestamp=ts,
                token_usage_in=token_usage_in,
                token_usage_out=token_usage_out,
                cache_read_tokens=cache_read_tokens,
                cache_create_tokens=cache_create_tokens,
            )

        if not isinstance(content_blocks, list):
            return None

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []

        for block in content_blocks:
            if isinstance(block, str):
                text_parts.append(block)
                continue
            if not isinstance(block, dict):
                continue

            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "thinking":
                thinking = block.get("thinking") or block.get("text") or ""
                if thinking:
                    text_parts.append(thinking[:500])
            elif btype == "tool_use":
                tc = ToolCall(
                    name=block.get("name", "unknown"),
                    input=block.get("input", {}),
                    tool_use_id=block.get("id"),
                )
                tool_calls.append(tc)

        content = "\n".join(text_parts).strip()
        if not content and not tool_calls:
            return None

        return Turn(
            role="assistant",
            content=content,
            tool_calls=tool_calls,
            timestamp=ts,
            token_usage_in=token_usage_in,
            token_usage_out=token_usage_out,
            cache_read_tokens=cache_read_tokens,
            cache_create_tokens=cache_create_tokens,
        )

    def _parse_summary(
        self,
        event: dict,
        message: dict,
        ts: str | None, *,
        token_usage_in: int = 0, token_usage_out: int = 0,
        cache_read_tokens: int = 0, cache_create_tokens: int = 0,
    ) -> Turn | None:
        # Try multiple locations for summary text
        text = _coerce_text(event.get("summary"))
        if not text:
            text = _coerce_text(message.get("summary"))
        if not text:
            content = message.get("content")
            if isinstance(content, list):
                text = _collect_text(content)
            else:
                text = _coerce_text(content)

        if not text:
            return None

        return Turn(
            role="summary",
            content=text,
            timestamp=ts,
            token_usage_in=token_usage_in,
            token_usage_out=token_usage_out,
            cache_read_tokens=cache_read_tokens,
            cache_create_tokens=cache_create_tokens,
        )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _collect_text(blocks: Any) -> str:
    """Concatenate text from content blocks."""
    if isinstance(blocks, str):
        return blocks
    if not isinstance(blocks, list):
        return _coerce_text(blocks)

    pieces: list[str] = []
    for block in blocks:
        if isinstance(block, str):
            pieces.append(block)
        elif isinstance(block, dict):
            btype = block.get("type")
            if btype == "text":
                pieces.append(block.get("text", ""))
            elif btype == "tool_result":
                inner = block.get("content", "")
                if isinstance(inner, list):
                    for sub in inner:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            pieces.append(sub.get("text", ""))
                        elif isinstance(sub, str):
                            pieces.append(sub)
                elif isinstance(inner, str):
                    pieces.append(inner)
    return "\n".join(pieces)


def _coerce_text(value: Any) -> str:
    """Coerce any value to a string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                t = _coerce_text(item.get("text") or item.get("content") or item)
            else:
                t = _coerce_text(item)
            if t:
                parts.append(t)
        return "\n".join(parts).strip()
    if isinstance(value, dict):
        try:
            return json.dumps(value, ensure_ascii=True, sort_keys=True)
        except Exception:
            return str(value).strip()
    return str(value).strip()
