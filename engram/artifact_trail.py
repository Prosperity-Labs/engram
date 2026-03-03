"""Parse Claude Code JSONL session files into artifact timelines.

Reconstructs a chronological trail of tool calls (reads, writes, edits,
bash commands) from raw JSONL data — no database required.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class ArtifactEvent:
    sequence: int
    timestamp: datetime
    tool_type: str
    file_path: Optional[str]
    old_content: Optional[str] = None
    new_content: Optional[str] = None
    command: Optional[str] = None
    exit_code: Optional[int] = None
    stdout: Optional[str] = None
    description: Optional[str] = None
    is_error: bool = False
    tool_use_id: str = ""


_EXIT_CODE_RE = re.compile(r"^Exit code (\d+)")
_TOOL_NAMES = frozenset({"Write", "Edit", "Read", "Bash", "Glob", "Grep"})


def parse_session_trail(jsonl_path: Path) -> list[ArtifactEvent]:
    """Parse a JSONL session file and return ordered list of ArtifactEvents."""
    tool_uses: dict[str, tuple[int, dict, datetime]] = {}
    results: dict[str, dict] = {}
    events: list[ArtifactEvent] = []
    seq = 0

    with open(jsonl_path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type")
            ts_str = entry.get("timestamp")
            ts = _parse_ts(ts_str) if ts_str else None
            message = entry.get("message")
            if not message:
                continue
            content_blocks = message.get("content")
            if not isinstance(content_blocks, list):
                continue

            if entry_type == "assistant":
                for block in content_blocks:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue
                    name = block.get("name", "")
                    if name not in _TOOL_NAMES:
                        continue
                    tool_id = block.get("id", "")
                    seq += 1
                    tool_uses[tool_id] = (seq, block, ts or datetime.min.replace(tzinfo=timezone.utc))

            elif entry_type == "user":
                for block in content_blocks:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_result":
                        continue
                    tool_id = block.get("tool_use_id", "")
                    results[tool_id] = block

    for tool_id, (sequence, block, ts) in tool_uses.items():
        name = block.get("name", "")
        inp = block.get("input", {})
        result_block = results.get(tool_id, {})
        result_content = result_block.get("content", "")
        if isinstance(result_content, list):
            result_content = "\n".join(
                b.get("text", "") for b in result_content if isinstance(b, dict)
            )
        is_error = bool(result_block.get("is_error", False))

        event = ArtifactEvent(
            sequence=sequence,
            timestamp=ts,
            tool_type=name.upper(),
            file_path=inp.get("file_path"),
            tool_use_id=tool_id,
            is_error=is_error,
        )

        if name == "Write":
            event.new_content = inp.get("content")
        elif name == "Edit":
            event.old_content = inp.get("old_string")
            event.new_content = inp.get("new_string")
        elif name == "Bash":
            event.command = inp.get("command")
            event.description = inp.get("description")
            event.stdout = result_content or None
            m = _EXIT_CODE_RE.match(result_content)
            if m:
                event.exit_code = int(m.group(1))
                event.is_error = event.exit_code != 0
            elif result_content and not is_error:
                event.exit_code = 0
        elif name in ("Glob", "Grep"):
            event.file_path = inp.get("path") or inp.get("file_path")

        events.append(event)

    events.sort(key=lambda e: e.sequence)
    return events


def find_session_jsonl(session_id: str) -> Optional[Path]:
    """Find the JSONL file for a session ID by searching ~/.claude/projects/."""
    claude_dir = Path.home() / ".claude" / "projects"
    if not claude_dir.is_dir():
        return None

    for jsonl in claude_dir.rglob(f"{session_id}.jsonl"):
        return jsonl

    for directory in claude_dir.rglob(session_id):
        if directory.is_dir():
            jsonls = sorted(directory.glob("*.jsonl"))
            if jsonls:
                return jsonls[-1]

    return None


def format_trail(events: list[ArtifactEvent]) -> str:
    """Format events as a readable timeline string."""
    if not events:
        return "No artifact events found."

    lines: list[str] = []
    t0 = events[0].timestamp

    for ev in events:
        delta = ev.timestamp - t0
        minutes, seconds = divmod(int(delta.total_seconds()), 60)
        ts_label = f"{minutes:02d}:{seconds:02d}"

        target = _event_target(ev)
        detail = _event_detail(ev)
        suffix = f"  {detail}" if detail else ""

        lines.append(f"#{ev.sequence:03d} [{ts_label}] {ev.tool_type:<6} {target}{suffix}")

    return "\n".join(lines)


def _event_target(ev: ArtifactEvent) -> str:
    if ev.tool_type == "BASH":
        cmd = (ev.command or "")[:60]
        return cmd
    if ev.file_path:
        return Path(ev.file_path).name
    return ""


def _event_detail(ev: ArtifactEvent) -> str:
    if ev.tool_type == "BASH":
        if ev.exit_code is not None:
            marker = "!" if ev.is_error else ""
            return f"-> exit {ev.exit_code}{marker}"
        return ""
    if ev.tool_type == "EDIT" and ev.old_content is not None and ev.new_content is not None:
        removed = ev.old_content.count("\n") + 1
        added = ev.new_content.count("\n") + 1
        return f"(+{added}/-{removed} lines)"
    if ev.tool_type == "WRITE" and ev.new_content is not None:
        added = ev.new_content.count("\n") + 1
        return f"({added} lines)"
    return ""


def _parse_ts(raw: str) -> datetime:
    raw = raw.replace("Z", "+00:00")
    return datetime.fromisoformat(raw)
