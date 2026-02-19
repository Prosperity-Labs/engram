from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .session_db import SessionDB


class LiveIndexer:
    def __init__(self):
        self.db = SessionDB()
        self._offsets: dict[str, int] = {}
        self._seq: dict[str, int] = {}
        self._rollback_bytes: dict[str, int] = {}
        self._stats = {"polls": 0, "total_new_messages": 0, "sessions_seen": set()}

    def discover_active_sessions(self) -> list[Path]:
        base = Path.home() / ".claude" / "projects"
        if not base.exists():
            return []

        cutoff = time.time() - (2 * 60 * 60)
        active: list[tuple[float, Path]] = []
        for path in base.glob("*/*.jsonl"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime >= cutoff:
                active.append((mtime, path))

        active.sort(key=lambda item: item[0], reverse=True)
        return [path for _, path in active]

    def poll(self) -> dict:
        self._stats["polls"] += 1

        sessions = self.discover_active_sessions()
        new_messages = 0
        errors = 0

        for filepath in sessions:
            session_id = filepath.stem
            self._stats["sessions_seen"].add(session_id)

            try:
                size = filepath.stat().st_size

                if session_id not in self._offsets:
                    self._offsets[session_id] = self._bootstrap_offset(session_id, filepath)

                if session_id not in self._seq:
                    self._seq[session_id] = self.db.get_last_sequence(session_id)

                offset = self._offsets[session_id]
                if size < offset:
                    offset = 0
                    self._offsets[session_id] = 0

                if size == offset:
                    continue

                with filepath.open("rb") as f:
                    f.seek(offset)
                    data = f.read(size - offset)

                messages = self._parse_new_lines(data, session_id)
                rollback = self._rollback_bytes.get(session_id, 0)
                consumed = len(data) - rollback
                if consumed < 0:
                    consumed = 0
                self._offsets[session_id] = offset + consumed

                if not messages:
                    continue

                self._ensure_session(filepath, session_id)
                start_seq = self._seq[session_id] + 1
                inserted = self.db.insert_messages(session_id, messages, start_seq)
                self._seq[session_id] = start_seq + inserted - 1

                new_messages += inserted
            except Exception:
                errors += 1

        self._stats["total_new_messages"] += new_messages
        return {
            "sessions_polled": len(sessions),
            "new_messages": new_messages,
            "errors": errors,
        }

    def _bootstrap_offset(self, session_id: str, filepath: Path) -> int:
        last_seq = self.db.get_last_sequence(session_id)
        self._seq[session_id] = last_seq

        if last_seq > 0:
            try:
                return filepath.stat().st_size
            except OSError:
                return 0
        return 0

    def _parse_new_lines(self, data: bytes, session_id: str) -> list[dict]:
        self._rollback_bytes[session_id] = 0
        if not data:
            return []

        working = data
        if not working.endswith(b"\n"):
            last_nl = working.rfind(b"\n")
            if last_nl == -1:
                self._rollback_bytes[session_id] = len(working)
                return []
            self._rollback_bytes[session_id] = len(working) - last_nl - 1
            working = working[: last_nl + 1]

        decoded = working.decode("utf-8", errors="replace")
        parsed_messages: list[dict[str, Any]] = []

        for raw_line in decoded.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = item.get("type")
            timestamp = item.get("timestamp")
            message = item.get("message") or {}

            if msg_type == "user":
                content = self._extract_user_content(message.get("content") or [])
                if content:
                    parsed_messages.append(
                        {
                            "role": "user",
                            "content": content,
                            "timestamp": timestamp,
                            "tool_name": None,
                            "token_usage_in": None,
                            "token_usage_out": None,
                        }
                    )

            elif msg_type == "assistant":
                usage = message.get("usage") or {}
                token_in = (
                    int(usage.get("input_tokens") or 0)
                    + int(usage.get("cache_read_input_tokens") or 0)
                    + int(usage.get("cache_creation_input_tokens") or 0)
                )
                token_out = int(usage.get("output_tokens") or 0)

                content_blocks = message.get("content") or []
                if isinstance(content_blocks, str):
                    parsed_messages.append({
                        "role": "assistant",
                        "content": content_blocks,
                        "timestamp": timestamp,
                        "tool_name": None,
                        "token_usage_in": token_in,
                        "token_usage_out": token_out,
                    })
                    continue
                for block in content_blocks:
                    if isinstance(block, str):
                        parsed_messages.append({
                            "role": "assistant",
                            "content": block,
                            "timestamp": timestamp,
                            "tool_name": None,
                            "token_usage_in": token_in,
                            "token_usage_out": token_out,
                        })
                        token_in, token_out = 0, 0
                        continue
                    if not isinstance(block, dict):
                        continue
                    block_type = block.get("type")
                    text = ""
                    tool_name = None

                    if block_type == "text":
                        text = self._coerce_text(block.get("text"))
                    elif block_type == "thinking":
                        text = self._coerce_text(block.get("thinking") or block.get("text"))
                    elif block_type == "tool_use":
                        tool_name = self._coerce_text(block.get("name")) or None
                        text = self._coerce_text(block.get("input"))

                    if text:
                        parsed_messages.append(
                            {
                                "role": "assistant",
                                "content": text,
                                "timestamp": timestamp,
                                "tool_name": tool_name,
                                "token_usage_in": token_in,
                                "token_usage_out": token_out,
                            }
                        )

            elif msg_type == "summary":
                summary_text = self._extract_summary_content(item, message)
                if summary_text:
                    parsed_messages.append(
                        {
                            "role": "summary",
                            "content": summary_text,
                            "timestamp": timestamp,
                            "tool_name": None,
                            "token_usage_in": None,
                            "token_usage_out": None,
                        }
                    )

        return parsed_messages

    def _ensure_session(self, filepath: Path, session_id: str):
        project_raw = filepath.parent.name
        project = self._clean_project_name(project_raw)
        self.db.upsert_session_meta(session_id, str(filepath), project)

    def cumulative_stats(self) -> dict:
        return {
            "polls": self._stats["polls"],
            "total_new_messages": self._stats["total_new_messages"],
            "sessions_seen": len(self._stats["sessions_seen"]),
        }

    def _extract_user_content(self, blocks: Any) -> str:
        if isinstance(blocks, str):
            return blocks.strip()
        if not isinstance(blocks, list):
            return self._coerce_text(blocks)
        parts: list[str] = []
        for block in blocks:
            if isinstance(block, str):
                parts.append(block)
                continue
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text = self._coerce_text(block.get("text"))
                if text:
                    parts.append(text)
            elif block_type == "tool_result":
                text = self._coerce_text(block.get("content"))
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()

    def _extract_summary_content(self, item: dict[str, Any], message: dict[str, Any]) -> str:
        direct = self._coerce_text(item.get("summary"))
        if direct:
            return direct

        msg_summary = self._coerce_text(message.get("summary"))
        if msg_summary:
            return msg_summary

        content = message.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                text = self._coerce_text(block.get("text") if isinstance(block, dict) else block)
                if text:
                    parts.append(text)
            return "\n".join(parts).strip()

        return self._coerce_text(content)

    def _clean_project_name(self, raw: str) -> str:
        if raw.startswith("-home-"):
            segments = [seg for seg in raw.split("-") if seg]
            if segments:
                return segments[-1]
        return raw

    def _coerce_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                if isinstance(item, dict):
                    text = self._coerce_text(item.get("text") or item.get("content") or item)
                else:
                    text = self._coerce_text(item)
                if text:
                    parts.append(text)
            return "\n".join(parts).strip()
        if isinstance(value, dict):
            try:
                return json.dumps(value, ensure_ascii=True, sort_keys=True)
            except Exception:
                return str(value).strip()
        return str(value).strip()
