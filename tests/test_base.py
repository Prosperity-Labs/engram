"""Tests for the base adapter classes."""

from engram.adapters.base import AgentAdapter, EngramSession, Turn, ToolCall


class TestToolCall:
    def test_create(self):
        tc = ToolCall(name="Read", input={"file_path": "/foo"})
        assert tc.name == "Read"
        assert tc.input == {"file_path": "/foo"}
        assert tc.output is None
        assert tc.tool_use_id is None

    def test_with_output(self):
        tc = ToolCall(name="Bash", input={"command": "ls"}, output="file1\nfile2")
        assert tc.output == "file1\nfile2"


class TestTurn:
    def test_user_turn(self):
        t = Turn(role="user", content="Fix the bug")
        assert t.role == "user"
        assert t.content == "Fix the bug"
        assert t.tool_calls == []
        assert t.token_usage_in == 0

    def test_assistant_turn_with_tools(self):
        t = Turn(
            role="assistant",
            content="Looking at the file.",
            tool_calls=[
                ToolCall(name="Read", input={"file_path": "/src/app.ts"}),
                ToolCall(name="Edit", input={"file_path": "/src/app.ts"}),
            ],
            token_usage_in=5000,
            token_usage_out=200,
        )
        assert len(t.tool_calls) == 2
        assert t.token_usage_in == 5000


class TestEngramSession:
    def test_empty_session(self):
        s = EngramSession(session_id="test", agent="claude_code")
        assert s.message_count == 0
        assert s.total_tokens_in == 0
        assert s.total_tokens_out == 0
        assert s.tool_call_count() == 0

    def test_session_with_turns(self):
        s = EngramSession(session_id="test", agent="codex", project="myapp")
        s.turns = [
            Turn(role="user", content="hello", token_usage_in=100),
            Turn(
                role="assistant",
                content="hi",
                tool_calls=[ToolCall(name="Read", input={})],
                token_usage_in=500,
                token_usage_out=50,
            ),
        ]
        assert s.message_count == 2
        assert s.total_tokens_in == 600
        assert s.total_tokens_out == 50
        assert s.tool_call_count() == 1

    def test_to_message_dicts_no_tools(self):
        s = EngramSession(session_id="test", agent="claude_code")
        s.turns = [
            Turn(role="user", content="hello", timestamp="2026-01-01T00:00:00Z"),
        ]
        msgs = s.to_message_dicts()
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "hello"
        assert msgs[0]["tool_name"] is None

    def test_to_message_dicts_with_tools(self):
        s = EngramSession(session_id="test", agent="claude_code")
        s.turns = [
            Turn(
                role="assistant",
                content="Looking at it.",
                tool_calls=[
                    ToolCall(name="Read", input={"file_path": "/foo"}),
                    ToolCall(name="Edit", input={"file_path": "/bar"}),
                ],
                token_usage_in=1000,
                token_usage_out=100,
            ),
        ]
        msgs = s.to_message_dicts()
        # text + 2 tool calls = 3 messages
        assert len(msgs) == 3
        assert msgs[0]["tool_name"] is None
        assert msgs[0]["content"] == "Looking at it."
        assert msgs[0]["token_usage_in"] == 1000
        assert msgs[1]["tool_name"] == "Read"
        assert msgs[1]["token_usage_in"] == 0  # only first gets tokens
        assert msgs[2]["tool_name"] == "Edit"

    def test_to_message_dicts_tool_only(self):
        """Turn with empty text + tool calls should not emit empty text row."""
        s = EngramSession(session_id="test", agent="claude_code")
        s.turns = [
            Turn(
                role="assistant",
                content="",
                tool_calls=[ToolCall(name="Bash", input={"command": "ls"})],
            ),
        ]
        msgs = s.to_message_dicts()
        assert len(msgs) == 1
        assert msgs[0]["tool_name"] == "Bash"
