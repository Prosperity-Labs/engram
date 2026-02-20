"""Tests for the Claude Code adapter."""

from engram.adapters.claude_code import ClaudeCodeAdapter


class TestClaudeCodeAdapterParsing:
    def test_parse_fixture(self, claude_code_session):
        adapter = ClaudeCodeAdapter()
        session = adapter.parse_file(str(claude_code_session))

        assert session.session_id == "test-claude-session-001"
        assert session.agent == "claude_code"
        assert session.message_count > 0
        assert session.start_time == "2026-02-20T10:00:00Z"
        assert session.end_time == "2026-02-20T10:01:00Z"

    def test_turns_parsed_correctly(self, claude_code_session):
        adapter = ClaudeCodeAdapter()
        session = adapter.parse_file(str(claude_code_session))

        roles = [t.role for t in session.turns]
        assert "user" in roles
        assert "assistant" in roles
        assert "summary" in roles

    def test_tool_calls_extracted(self, claude_code_session):
        adapter = ClaudeCodeAdapter()
        session = adapter.parse_file(str(claude_code_session))

        tool_turns = [t for t in session.turns if t.tool_calls]
        assert len(tool_turns) >= 2  # Read + Edit, Bash

        tool_names = []
        for t in tool_turns:
            for tc in t.tool_calls:
                tool_names.append(tc.name)
        assert "Read" in tool_names
        assert "Edit" in tool_names
        assert "Bash" in tool_names

    def test_token_usage(self, claude_code_session):
        adapter = ClaudeCodeAdapter()
        session = adapter.parse_file(str(claude_code_session))

        assert session.total_tokens_in > 0
        # cache_read_input_tokens should be included
        assistant_turns = [t for t in session.turns if t.role == "assistant"]
        first_assistant = assistant_turns[0]
        assert first_assistant.token_usage_in == 2000  # 1500 + 500 cache_read

    def test_to_message_dicts_bridge(self, claude_code_session):
        adapter = ClaudeCodeAdapter()
        session = adapter.parse_file(str(claude_code_session))
        msgs = session.to_message_dicts()

        assert len(msgs) > 0
        assert all("role" in m for m in msgs)
        assert all("content" in m for m in msgs)

        tool_msgs = [m for m in msgs if m["tool_name"]]
        assert len(tool_msgs) >= 3  # Read, Edit, Bash

    def test_summary_turn(self, claude_code_session):
        adapter = ClaudeCodeAdapter()
        session = adapter.parse_file(str(claude_code_session))

        summaries = [t for t in session.turns if t.role == "summary"]
        assert len(summaries) == 1
        assert "login bug" in summaries[0].content.lower()


class TestClaudeCodeAdapterProject:
    def test_guess_project_from_path(self):
        adapter = ClaudeCodeAdapter()
        project = adapter.guess_project(
            "/home/user/.claude/projects/my-project/abc123.jsonl"
        )
        assert project == "my-project"

    def test_guess_project_no_projects_dir(self):
        adapter = ClaudeCodeAdapter()
        project = adapter.guess_project("/some/random/path/session.jsonl")
        assert project is None


class TestClaudeCodeAdapterDiscovery:
    def test_discover_returns_list(self):
        adapter = ClaudeCodeAdapter()
        sessions = adapter.discover_sessions()
        # Should return a list (may be empty if no Claude Code installed)
        assert isinstance(sessions, list)


class TestClaudeCodeAdapterIndexing:
    def test_index_via_adapter(self, tmp_db, claude_code_session):
        """Test that index_session uses the adapter and produces correct results."""
        result = tmp_db.index_session(claude_code_session)
        assert result["messages_indexed"] > 0

        # Verify data in DB
        assert tmp_db.is_indexed("test-claude-session-001")
        stats = tmp_db.stats()
        assert stats["total_sessions"] == 1
        assert stats["total_messages"] > 0

    def test_index_from_session(self, tmp_db, claude_code_session):
        """Test index_from_session with adapter output."""
        adapter = ClaudeCodeAdapter()
        session = adapter.parse_file(str(claude_code_session))
        result = tmp_db.index_from_session(session)

        assert result["messages_indexed"] > 0
        assert tmp_db.is_indexed(session.session_id)

    def test_search_after_index(self, tmp_db, claude_code_session):
        """Test FTS search works on adapter-indexed data."""
        tmp_db.index_session(claude_code_session)

        results = tmp_db.search("login bug", limit=5)
        assert len(results) > 0
