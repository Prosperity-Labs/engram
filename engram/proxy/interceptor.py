"""Engram proxy interceptor — mitmproxy addon for Anthropic API calls.

Logs every request/response pair to SQLite. Phase 1: observe only, no modification.

Usage with mitmproxy reverse proxy mode:
    mitmdump --mode reverse:https://api.anthropic.com --listen-port 9080 \
             -s engram/proxy/interceptor.py

Then point Claude Code at the proxy:
    export ANTHROPIC_BASE_URL=http://localhost:9080
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from mitmproxy import http

# Cost model (Opus pricing)
_COST_PER_M = {
    "input": 15.0,
    "output": 75.0,
    "cache_read": 1.50,
    "cache_create": 18.75,
}

DB_PATH = Path.home() / ".config" / "engram" / "sessions.db"


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English text."""
    return len(text) // 4 if text else 0


def _extract_project(body: dict) -> str | None:
    """Try to detect project from system prompt content."""
    system = body.get("system", "")
    if isinstance(system, list):
        # system can be a list of content blocks
        system = " ".join(
            block.get("text", "") for block in system if isinstance(block, dict)
        )
    if not system:
        return None

    # Look for common project indicators in system prompt
    # CLAUDE.md paths, working directory mentions, etc.
    patterns = [
        r"working directory[:\s]+([^\n]+)",
        r"Primary working directory[:\s]+([^\n]+)",
        r"project[:\s]+([^\n]+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, system, re.IGNORECASE)
        if m:
            path = m.group(1).strip()
            # Extract last meaningful directory name
            parts = [p for p in path.rstrip("/").split("/") if p]
            if parts:
                return parts[-1]
    return None


def _extract_tools_from_request(body: dict) -> list[str]:
    """Extract tool names available in the request."""
    tools = body.get("tools", [])
    return [t.get("name", "unknown") for t in tools if isinstance(t, dict)]


def _extract_tool_use_from_response(body: dict) -> list[str]:
    """Extract tool_use blocks from the response content."""
    content = body.get("content", [])
    tool_names = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tool_names.append(block.get("name", "unknown"))
    return tool_names


class EngramInterceptor:
    """mitmproxy addon that logs Anthropic API calls to Engram's SQLite DB."""

    def __init__(self):
        self.db_path = str(DB_PATH)
        self._ensure_schema()
        self._call_count = 0
        self._total_input = 0
        self._total_output = 0
        self._total_cost = 0.0
        self._pending: dict[str, dict] = {}  # flow.id -> request data

    def requestheaders(self, flow: http.HTTPFlow) -> None:
        """Disable streaming so we can read full request/response bodies."""
        flow.request.stream = False

    def responseheaders(self, flow: http.HTTPFlow) -> None:
        """Disable response streaming so we can read the full body."""
        flow.response.stream = False

    def _ensure_schema(self) -> None:
        """Create proxy_calls table if it doesn't exist."""
        schema_path = Path(__file__).parent / "schema.sql"
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(schema_path.read_text())
            conn.commit()
        finally:
            conn.close()

    def _save_call(self, data: dict) -> None:
        """Insert a proxy call record into SQLite."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO proxy_calls
                    (id, timestamp, model, system_prompt_tokens, message_count,
                     input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
                     cost_estimate_usd, tools_used, stop_reason, session_id, project,
                     request_bytes, response_bytes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["id"],
                    data["timestamp"],
                    data.get("model"),
                    data.get("system_prompt_tokens", 0),
                    data.get("message_count", 0),
                    data.get("input_tokens", 0),
                    data.get("output_tokens", 0),
                    data.get("cache_read_tokens", 0),
                    data.get("cache_creation_tokens", 0),
                    data.get("cost_estimate_usd", 0.0),
                    json.dumps(data.get("tools_used", [])),
                    data.get("stop_reason"),
                    data.get("session_id"),
                    data.get("project"),
                    data.get("request_bytes", 0),
                    data.get("response_bytes", 0),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def request(self, flow: http.HTTPFlow) -> None:
        """Intercept outgoing request to Anthropic API."""
        # Only intercept messages endpoint
        if "/v1/messages" not in flow.request.path:
            return

        try:
            body = json.loads(flow.request.content)
        except (json.JSONDecodeError, TypeError):
            return

        # Disable streaming so we get a single JSON response we can parse
        if body.get("stream"):
            body["stream"] = False
            flow.request.content = json.dumps(body).encode()

        # Extract request metadata
        model = body.get("model", "unknown")
        messages = body.get("messages", [])
        system = body.get("system", "")

        # Estimate system prompt tokens
        if isinstance(system, list):
            system_text = " ".join(
                block.get("text", "") for block in system if isinstance(block, dict)
            )
        else:
            system_text = system or ""
        system_tokens = _estimate_tokens(system_text)

        # Available tools
        available_tools = _extract_tools_from_request(body)

        # Project detection
        project = _extract_project(body)

        # Store pending request data keyed by flow id
        self._pending[flow.id] = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "system_prompt_tokens": system_tokens,
            "message_count": len(messages),
            "available_tools": available_tools,
            "project": project,
            "request_bytes": len(flow.request.content) if flow.request.content else 0,
        }

    def response(self, flow: http.HTTPFlow) -> None:
        """Intercept response from Anthropic API."""
        if flow.id not in self._pending:
            return

        req_data = self._pending.pop(flow.id)

        try:
            body = json.loads(flow.response.content)
        except (json.JSONDecodeError, TypeError):
            # Still save what we have from the request
            self._save_call(req_data)
            return

        # Extract usage from response
        usage = body.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)
        cache_create = usage.get("cache_creation_input_tokens", 0)

        # Calculate cost
        cost = (
            input_tokens * _COST_PER_M["input"]
            + output_tokens * _COST_PER_M["output"]
            + cache_read * _COST_PER_M["cache_read"]
            + cache_create * _COST_PER_M["cache_create"]
        ) / 1_000_000

        # Extract what tools the model called
        tools_used = _extract_tool_use_from_response(body)

        stop_reason = body.get("stop_reason")

        # Merge response data
        call_data = {
            **req_data,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read,
            "cache_creation_tokens": cache_create,
            "cost_estimate_usd": round(cost, 6),
            "tools_used": tools_used,
            "stop_reason": stop_reason,
            "response_bytes": len(flow.response.content) if flow.response.content else 0,
        }

        self._save_call(call_data)

        # Update running totals
        self._call_count += 1
        self._total_input += input_tokens
        self._total_output += output_tokens
        self._total_cost += cost

        # Print one-line summary
        model_short = (call_data["model"] or "?").split("-")[-1][:10]
        tools_str = ",".join(tools_used[:3]) if tools_used else "-"
        if len(tools_used) > 3:
            tools_str += f"+{len(tools_used)-3}"
        proj = call_data.get("project") or "?"

        print(
            f"[{self._call_count:>4}] {model_short:<10} "
            f"in={input_tokens:>7,} out={output_tokens:>6,} "
            f"cache={cache_read:>7,} "
            f"${cost:.4f} "
            f"tools=[{tools_str}] "
            f"stop={stop_reason} "
            f"proj={proj}"
        )


# mitmproxy addon entry point
addons = [EngramInterceptor()]
