"""Tests for natural language query rewriting."""

import pytest
from engram.query_rewriter import (
    detect_recall_intent,
    expand_keywords,
    extract_keywords,
    rewrite_query,
)


class TestExtractKeywords:
    def test_removes_stopwords(self):
        kw = extract_keywords("how did we configure hooks last time")
        assert "how" not in kw
        assert "did" not in kw
        assert "we" not in kw
        assert "configure" in kw
        assert "hooks" in kw

    def test_caps_at_five(self):
        kw = extract_keywords("auth login jwt token session webhook escrow deposit")
        assert len(kw) <= 5

    def test_preserves_order(self):
        kw = extract_keywords("webhook escrow authentication")
        assert kw == ["webhook", "escrow", "authentication"]

    def test_deduplicates(self):
        kw = extract_keywords("hooks hooks hooks configure")
        assert kw.count("hooks") == 1

    def test_handles_empty_after_stopwords(self):
        kw = extract_keywords("how do I do this")
        assert len(kw) > 0  # fallback to longest words

    def test_handles_code_identifiers(self):
        kw = extract_keywords("what is SessionDB._connect doing")
        assert "sessiondb._connect" in kw or "sessiondb" in kw


class TestExpandKeywords:
    def test_adds_synonyms(self):
        expanded = expand_keywords(["auth"])
        assert "authentication" in expanded or "login" in expanded

    def test_original_first(self):
        expanded = expand_keywords(["hooks"])
        assert expanded[0] == "hooks"

    def test_caps_at_eight(self):
        expanded = expand_keywords(["auth", "hooks", "config", "error", "test"])
        assert len(expanded) <= 8

    def test_no_duplicates(self):
        expanded = expand_keywords(["auth", "authentication"])
        assert len(expanded) == len(set(e.lower() for e in expanded))


class TestRewriteQuery:
    def test_full_pipeline(self):
        result = rewrite_query("how did we configure hooks last time")
        assert "keywords" in result
        assert "expanded" in result
        assert "fts_queries" in result
        assert "configure" in result["keywords"]
        assert "hooks" in result["keywords"]

    def test_fts_queries_are_quoted(self):
        result = rewrite_query("find authentication errors")
        for q in result["fts_queries"]:
            assert q.startswith('"') and q.endswith('"')

    def test_escrow_webhook_query(self):
        result = rewrite_query("what broke in the escrow webhook sessions")
        assert "escrow" in result["keywords"]
        assert "webhook" in result["keywords"]

    def test_authentication_sessions_query(self):
        result = rewrite_query("find sessions where we touched authentication")
        assert "authentication" in result["keywords"]
        # Should expand to include related terms
        assert any(
            kw in result["expanded"]
            for kw in ["auth", "login", "JWT"]
        )


class TestDetectRecallIntent:
    def test_we_figured_this_out(self):
        r = detect_recall_intent("we already figured out the auth token refresh")
        assert r is not None
        assert "auth" in r["keywords"] or "token" in r["keywords"]
        assert r["topic"]  # should have extracted the topic

    def test_how_did_we_do(self):
        r = detect_recall_intent("how did we do the database migration?")
        assert r is not None
        assert "database" in r["keywords"] or "migration" in r["keywords"]

    def test_what_was_the_command_for(self):
        r = detect_recall_intent("what was the command for deploying to staging?")
        assert r is not None
        assert "deploying" in r["keywords"] or "staging" in r["keywords"]

    def test_we_did_this_before(self):
        r = detect_recall_intent("we did this before: configuring the webhook")
        assert r is not None
        assert "configuring" in r["keywords"] or "webhook" in r["keywords"]

    def test_remember_when(self):
        r = detect_recall_intent("remember when we fixed the escrow timeout bug?")
        assert r is not None
        assert "escrow" in r["keywords"] or "timeout" in r["keywords"]

    def test_didnt_we_already(self):
        r = detect_recall_intent("didn't we already solve the rate limiting issue?")
        assert r is not None
        assert "rate" in r["keywords"] or "limiting" in r["keywords"]

    def test_last_time_we(self):
        r = detect_recall_intent("last time we configured the CI pipeline it broke")
        assert r is not None
        assert "configured" in r["keywords"] or "pipeline" in r["keywords"]

    def test_we_solved_this(self):
        r = detect_recall_intent("we solved this — the JWT expiry problem")
        assert r is not None
        assert "jwt" in r["keywords"] or "expiry" in r["keywords"]

    def test_no_recall_intent(self):
        assert detect_recall_intent("please add a login button") is None
        assert detect_recall_intent("fix the bug in auth.py") is None
        assert detect_recall_intent("what is the current time?") is None

    def test_wasnt_there(self):
        r = detect_recall_intent("wasn't there a script for bulk embedding?")
        assert r is not None
        assert "script" in r["keywords"] or "embedding" in r["keywords"]

    def test_we_ve_done_this(self):
        r = detect_recall_intent("we've done this before with the proxy setup")
        assert r is not None
        assert "proxy" in r["keywords"] or "setup" in r["keywords"]
