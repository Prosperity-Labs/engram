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
