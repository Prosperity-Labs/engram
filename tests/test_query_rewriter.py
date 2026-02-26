"""Tests for natural language query rewriting."""

import pytest
from engram.query_rewriter import extract_keywords, expand_keywords, rewrite_query


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
