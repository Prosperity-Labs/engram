"""Shared test fixtures for Engram tests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from engram.recall.session_db import SessionDB


@pytest.fixture
def tmp_db(tmp_path):
    """Fresh SQLite database in a temp directory."""
    return SessionDB(db_path=tmp_path / "test.db")


@pytest.fixture
def fixtures_dir():
    """Path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def claude_code_session(tmp_path):
    """Create a minimal Claude Code JSONL session file."""
    session_id = "test-claude-session-001"
    filepath = tmp_path / "projects" / "test-project" / f"{session_id}.jsonl"
    filepath.parent.mkdir(parents=True)

    events = [
        {
            "type": "user",
            "timestamp": "2026-02-20T10:00:00Z",
            "message": {
                "content": [{"type": "text", "text": "Fix the login bug"}],
                "usage": {},
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-02-20T10:00:05Z",
            "message": {
                "content": [
                    {"type": "text", "text": "I'll look at the login handler."},
                    {
                        "type": "tool_use",
                        "id": "tu_001",
                        "name": "Read",
                        "input": {"file_path": "/src/auth/login.ts"},
                    },
                ],
                "usage": {
                    "input_tokens": 1500,
                    "output_tokens": 200,
                    "cache_read_input_tokens": 500,
                },
            },
        },
        {
            "type": "user",
            "timestamp": "2026-02-20T10:00:10Z",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu_001",
                        "content": "export function login(req, res) { ... }",
                    }
                ],
                "usage": {},
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-02-20T10:00:15Z",
            "message": {
                "content": [
                    {"type": "text", "text": "Found the bug. Fixing now."},
                    {
                        "type": "tool_use",
                        "id": "tu_002",
                        "name": "Edit",
                        "input": {
                            "file_path": "/src/auth/login.ts",
                            "old_string": "old code",
                            "new_string": "new code",
                        },
                    },
                ],
                "usage": {"input_tokens": 3000, "output_tokens": 150},
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-02-20T10:00:20Z",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_003",
                        "name": "Bash",
                        "input": {"command": "npm test"},
                    },
                ],
                "usage": {"input_tokens": 500, "output_tokens": 50},
            },
        },
        {
            "type": "summary",
            "timestamp": "2026-02-20T10:01:00Z",
            "message": {
                "content": [
                    {"type": "text", "text": "Fixed login bug by correcting auth check."}
                ],
            },
        },
    ]

    with open(filepath, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    return filepath


@pytest.fixture
def claude_code_session_with_subagent(tmp_path):
    """Create a Claude Code JSONL session with subagent (Task/Explore) progress entries."""
    session_id = "test-subagent-session-001"
    filepath = tmp_path / "projects" / "test-project" / f"{session_id}.jsonl"
    filepath.parent.mkdir(parents=True)

    events = [
        # Main agent user message
        {
            "type": "user",
            "timestamp": "2026-03-03T17:12:00.000Z",
            "message": {
                "content": [{"type": "text", "text": "Find all API endpoints in the codebase"}],
                "usage": {},
            },
        },
        # Main agent launches Task tool
        {
            "type": "assistant",
            "timestamp": "2026-03-03T17:12:05.000Z",
            "message": {
                "content": [
                    {"type": "text", "text": "I'll search the codebase for API endpoints."},
                    {
                        "type": "tool_use",
                        "id": "toolu_01Main",
                        "name": "Task",
                        "input": {"prompt": "Find all API endpoints", "subagent_type": "Explore"},
                    },
                ],
                "usage": {"input_tokens": 2000, "output_tokens": 300},
            },
        },
        # Subagent progress: assistant with Grep tool call
        {
            "type": "progress",
            "parentToolUseID": "toolu_01Main",
            "data": {
                "type": "agent_progress",
                "agentId": "a2b9d82",
                "message": {
                    "type": "assistant",
                    "timestamp": "2026-03-03T17:13:00.000Z",
                    "message": {
                        "model": "claude-sonnet-4-5-20250929",
                        "content": [
                            {"type": "text", "text": "Let me search for route definitions."},
                            {
                                "type": "tool_use",
                                "id": "toolu_sub_001",
                                "name": "Grep",
                                "input": {"pattern": "app\\.(get|post|put|delete)\\(", "glob": "**/*.ts"},
                            },
                        ],
                        "usage": {"input_tokens": 500, "output_tokens": 100},
                    },
                },
            },
        },
        # Subagent progress: user (tool result)
        {
            "type": "progress",
            "parentToolUseID": "toolu_01Main",
            "data": {
                "type": "agent_progress",
                "agentId": "a2b9d82",
                "message": {
                    "type": "user",
                    "timestamp": "2026-03-03T17:13:05.000Z",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "toolu_sub_001",
                                "content": "src/routes/api.ts:15: app.get('/users')\nsrc/routes/api.ts:30: app.post('/users')",
                            }
                        ],
                    },
                },
            },
        },
        # Subagent progress: assistant with Read tool call
        {
            "type": "progress",
            "parentToolUseID": "toolu_01Main",
            "data": {
                "type": "agent_progress",
                "agentId": "a2b9d82",
                "message": {
                    "type": "assistant",
                    "timestamp": "2026-03-03T17:13:10.000Z",
                    "message": {
                        "model": "claude-sonnet-4-5-20250929",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "toolu_sub_002",
                                "name": "Read",
                                "input": {"file_path": "/src/routes/api.ts"},
                            },
                        ],
                        "usage": {"input_tokens": 800, "output_tokens": 50},
                    },
                },
            },
        },
        # Non-agent progress (should be ignored)
        {
            "type": "progress",
            "parentToolUseID": "toolu_01Main",
            "data": {
                "type": "tool_progress",
                "content": "Processing...",
            },
        },
        # Main agent continues after subagent completes
        {
            "type": "assistant",
            "timestamp": "2026-03-03T17:14:00.000Z",
            "message": {
                "content": [
                    {"type": "text", "text": "Found 2 API endpoints in the codebase."},
                ],
                "usage": {"input_tokens": 3000, "output_tokens": 200},
            },
        },
    ]

    with open(filepath, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    return filepath


@pytest.fixture
def codex_session(tmp_path):
    """Create a minimal Codex JSONL session file."""
    session_id = "019c-test-codex-session"
    filepath = tmp_path / "codex" / "sessions" / f"rollout-2026-02-20-{session_id}.jsonl"
    filepath.parent.mkdir(parents=True)

    events = [
        {
            "timestamp": "2026-02-20T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "timestamp": "2026-02-20T10:00:00Z",
                "cwd": "/home/user/project",
                "originator": "codex_cli_rs",
                "cli_version": "0.102.0",
                "source": "cli",
                "model_provider": "openai",
            },
        },
        {
            "timestamp": "2026-02-20T10:00:01Z",
            "type": "event_msg",
            "payload": {
                "type": "task_started",
                "turn_id": "turn-001",
                "model_context_window": 258400,
            },
        },
        {
            "timestamp": "2026-02-20T10:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Fix the deploy script"}],
            },
        },
        {
            "timestamp": "2026-02-20T10:00:05Z",
            "type": "event_msg",
            "payload": {
                "type": "agent_reasoning",
                "text": "Looking at deploy configuration",
            },
        },
        {
            "timestamp": "2026-02-20T10:00:05Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "arguments": '{"cmd":"cat deploy.sh"}',
                "call_id": "call_001",
            },
        },
        {
            "timestamp": "2026-02-20T10:00:06Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call_001",
                "output": "#!/bin/bash\necho 'deploying...'",
            },
        },
        {
            "timestamp": "2026-02-20T10:00:10Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 5000,
                        "cached_input_tokens": 2000,
                        "output_tokens": 300,
                        "reasoning_output_tokens": 50,
                        "total_tokens": 5300,
                    },
                },
            },
        },
        {
            "timestamp": "2026-02-20T10:00:15Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "Fixed the deploy script. The issue was a missing env var."}
                ],
            },
        },
    ]

    with open(filepath, "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    return filepath
