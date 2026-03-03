"""Tests for subagent/Task tool call indexing (P0 bug fix).

Verifies that progress entries from subagents (Explore, Plan, etc.)
are properly parsed, indexed, and searchable.
"""

from __future__ import annotations

import json

from engram.adapters.claude_code import ClaudeCodeAdapter
from engram.recall.live_indexer import LiveIndexer


class TestAdapterParsesProgressEntries:
    """ClaudeCodeAdapter extracts Turns from progress events."""

    def test_progress_assistant_with_tool_use(self):
        event = {
            "type": "progress",
            "parentToolUseID": "toolu_01Main",
            "data": {
                "type": "agent_progress",
                "agentId": "abc123",
                "message": {
                    "type": "assistant",
                    "timestamp": "2026-03-03T17:13:00.000Z",
                    "message": {
                        "model": "claude-sonnet-4-5-20250929",
                        "content": [
                            {"type": "text", "text": "Searching for endpoints."},
                            {
                                "type": "tool_use",
                                "id": "toolu_sub_001",
                                "name": "Grep",
                                "input": {"pattern": "createUser"},
                            },
                        ],
                        "usage": {"input_tokens": 500, "output_tokens": 100},
                    },
                },
            },
        }

        adapter = ClaudeCodeAdapter()
        result = adapter.parse_event(event)

        assert isinstance(result, list)
        assert len(result) == 1
        turn = result[0]
        assert turn.agent_id == "abc123"
        assert turn.role == "assistant"
        assert "Searching for endpoints" in turn.content
        assert len(turn.tool_calls) == 1
        assert turn.tool_calls[0].name == "Grep"
        assert turn.token_usage_in == 500
        assert turn.token_usage_out == 100

    def test_progress_user_tool_result(self):
        event = {
            "type": "progress",
            "parentToolUseID": "toolu_01Main",
            "data": {
                "type": "agent_progress",
                "agentId": "abc123",
                "message": {
                    "type": "user",
                    "timestamp": "2026-03-03T17:13:05.000Z",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "toolu_sub_001",
                                "content": "Found 3 matches",
                            }
                        ],
                    },
                },
            },
        }

        adapter = ClaudeCodeAdapter()
        result = adapter.parse_event(event)

        assert isinstance(result, list)
        assert len(result) == 1
        turn = result[0]
        assert turn.agent_id == "abc123"
        assert turn.role == "user"
        assert "Found 3 matches" in turn.content

    def test_non_agent_progress_ignored(self):
        event = {
            "type": "progress",
            "parentToolUseID": "toolu_01Main",
            "data": {
                "type": "tool_progress",
                "content": "Processing...",
            },
        }

        adapter = ClaudeCodeAdapter()
        result = adapter.parse_event(event)

        assert isinstance(result, list)
        assert len(result) == 0

    def test_parse_file_includes_subagent_turns(self, claude_code_session_with_subagent):
        adapter = ClaudeCodeAdapter()
        session = adapter.parse_file(str(claude_code_session_with_subagent))

        # Count subagent turns
        subagent_turns = [t for t in session.turns if t.agent_id is not None]
        main_turns = [t for t in session.turns if t.agent_id is None]

        assert len(subagent_turns) == 3  # 2 assistant + 1 user from subagent
        assert len(main_turns) >= 3  # user + assistant(Task) + assistant(final)

        # Verify agent_id propagation
        for turn in subagent_turns:
            assert turn.agent_id == "a2b9d82"


class TestLiveIndexerProgressHandling:
    """LiveIndexer parses progress entries and includes agent_id."""

    def test_indexes_progress_entries(self, claude_code_session_with_subagent, tmp_db):
        """Progress entries produce messages with agent_id in the database."""
        filepath = claude_code_session_with_subagent
        session_id = filepath.stem

        with open(filepath, "rb") as f:
            data = f.read()

        indexer = LiveIndexer()
        indexer.db = tmp_db
        messages = indexer._parse_new_lines(data, session_id)

        # Should have messages from both main agent and subagent
        subagent_msgs = [m for m in messages if m.get("agent_id") is not None]
        main_msgs = [m for m in messages if m.get("agent_id") is None]

        assert len(subagent_msgs) >= 3  # text + Grep + tool_result + Read
        assert len(main_msgs) >= 3

        # Verify agent_id set correctly
        for msg in subagent_msgs:
            assert msg["agent_id"] == "a2b9d82"

        # Verify tool names from subagent
        subagent_tools = [m["tool_name"] for m in subagent_msgs if m.get("tool_name")]
        assert "Grep" in subagent_tools
        assert "Read" in subagent_tools

    def test_non_agent_progress_skipped(self):
        """Progress entries without agent_progress type are skipped."""
        data = json.dumps({
            "type": "progress",
            "parentToolUseID": "toolu_01Main",
            "data": {"type": "tool_progress", "content": "Processing..."},
        }).encode() + b"\n"

        indexer = LiveIndexer()
        messages = indexer._parse_new_lines(data, "test-session")
        assert len(messages) == 0


class TestFtsSearchFindsSubagentContent:
    """Subagent messages are searchable via FTS."""

    def test_search_finds_subagent_tool_content(self, claude_code_session_with_subagent, tmp_db):
        adapter = ClaudeCodeAdapter()
        session = adapter.parse_file(str(claude_code_session_with_subagent))
        session.session_id = claude_code_session_with_subagent.stem
        tmp_db.index_from_session(session, claude_code_session_with_subagent)

        # Search for content that only exists in subagent messages
        results = tmp_db.search("route definitions")
        assert len(results) > 0
        assert any("route" in r["content"].lower() for r in results)

    def test_search_finds_subagent_tool_names(self, claude_code_session_with_subagent, tmp_db):
        adapter = ClaudeCodeAdapter()
        session = adapter.parse_file(str(claude_code_session_with_subagent))
        session.session_id = claude_code_session_with_subagent.stem
        tmp_db.index_from_session(session, claude_code_session_with_subagent)

        # Search for Grep tool which was only used by subagent
        results = tmp_db.search("Grep")
        assert len(results) > 0


class TestAgentIdStoredInDb:
    """agent_id column is properly stored and queryable."""

    def test_agent_id_stored(self, claude_code_session_with_subagent, tmp_db):
        adapter = ClaudeCodeAdapter()
        session = adapter.parse_file(str(claude_code_session_with_subagent))
        session.session_id = claude_code_session_with_subagent.stem
        tmp_db.index_from_session(session, claude_code_session_with_subagent)

        with tmp_db._connect() as conn:
            subagent_count = conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE agent_id IS NOT NULL"
            ).fetchone()["c"]
            main_count = conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE agent_id IS NULL"
            ).fetchone()["c"]

        assert subagent_count > 0
        assert main_count > 0


class TestExistingSessionsUnaffected:
    """Backward compatibility: existing sessions without subagents still work."""

    def test_existing_session_no_agent_id(self, claude_code_session, tmp_db):
        adapter = ClaudeCodeAdapter()
        session = adapter.parse_file(str(claude_code_session))
        session.session_id = claude_code_session.stem
        tmp_db.index_from_session(session, claude_code_session)

        with tmp_db._connect() as conn:
            rows = conn.execute(
                "SELECT agent_id FROM messages WHERE session_id = ?",
                (claude_code_session.stem,),
            ).fetchall()

        assert len(rows) > 0
        # All should have NULL agent_id
        for row in rows:
            assert row["agent_id"] is None

    def test_insert_messages_without_agent_id(self, tmp_db):
        """insert_messages works with dicts that don't include agent_id."""
        tmp_db.upsert_session_meta("legacy-session", "/tmp/legacy.jsonl")
        messages = [
            {
                "role": "user",
                "content": "Hello",
                "timestamp": "2026-01-01T00:00:00Z",
                "tool_name": None,
            }
        ]
        inserted = tmp_db.insert_messages("legacy-session", messages)
        assert inserted == 1

        with tmp_db._connect() as conn:
            row = conn.execute(
                "SELECT agent_id FROM messages WHERE session_id = 'legacy-session'"
            ).fetchone()
        assert row["agent_id"] is None
