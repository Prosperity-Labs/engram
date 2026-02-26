# Agent Spec: Cursor — MCP Server Natural Language Search

> **Branch:** `feat/nl-search-mcp`
> **Agent:** Cursor
> **Scope:** `engram/mcp_server.py` (modify) + `engram/query_rewriter.py` (new) + `tests/test_query_rewriter.py` (new)

---

## Context

The MCP server already exists at `engram/mcp_server.py` with 8 tools. The `engram_search` tool currently does raw FTS5 pass-through — user input gets sanitized and sent directly to SQLite FTS5.

This works for exact keyword searches but fails for natural language:
- "How did we configure hooks last time" → sanitizes to `"How" "did" "we" "configure" "hooks" "last" "time"` → FTS5 ANDs them all → 0 results
- What we want: extract `["hooks", "configure", "settings"]` → search each → merge + rank

Codex is separately wiring `engram install` to auto-configure the MCP server. Your job is the search intelligence.

---

## Task 1: Query Rewriter Module

**New file:** `engram/query_rewriter.py`

This module converts natural language queries into effective FTS5 searches. No LLM needed — pure keyword extraction + expansion.

```python
"""Query rewriter: natural language → keyword expansion → FTS5 queries.

Converts conversational queries into effective search terms.
No LLM required — uses stopword removal, synonym expansion, and
compound keyword detection.
"""

from __future__ import annotations

import re

# Common English stopwords that add no search value
STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "must",
    "i", "me", "my", "we", "our", "you", "your", "he", "she", "it",
    "they", "them", "their", "this", "that", "these", "those",
    "what", "which", "who", "whom", "when", "where", "why", "how",
    "not", "no", "nor", "but", "or", "and", "so", "if", "then",
    "of", "in", "on", "at", "to", "for", "with", "by", "from",
    "up", "out", "about", "into", "through", "during", "before", "after",
    "just", "also", "very", "too", "quite", "really", "only",
    "all", "any", "some", "every", "each", "both", "few", "more",
    "did", "last", "time", "find", "show", "get", "tell",
})

# Domain-specific synonym expansion for coding sessions
SYNONYMS: dict[str, list[str]] = {
    "auth": ["authentication", "login", "JWT", "token", "session"],
    "authentication": ["auth", "login", "JWT", "token"],
    "login": ["auth", "authentication", "signin"],
    "hook": ["hooks", "PreToolUse", "PostToolUse", "SessionStart", "SessionEnd"],
    "hooks": ["hook", "PreToolUse", "PostToolUse", "SessionStart", "SessionEnd"],
    "config": ["configuration", "settings", "setup", ".env"],
    "configure": ["config", "configuration", "settings", "setup"],
    "settings": ["config", "configuration", "settings.json"],
    "error": ["errors", "bug", "fix", "broke", "broken", "fail", "failed"],
    "bug": ["error", "fix", "broke", "broken", "fail"],
    "broke": ["error", "broken", "fail", "failed", "bug"],
    "test": ["tests", "testing", "pytest", "jest", "spec"],
    "deploy": ["deployment", "CI", "CD", "pipeline", "release"],
    "database": ["db", "SQL", "SQLite", "postgres", "migration", "schema"],
    "db": ["database", "SQL", "SQLite", "schema"],
    "api": ["endpoint", "route", "REST", "webhook"],
    "webhook": ["webhook", "endpoint", "callback", "hook"],
    "escrow": ["escrow", "deposit", "funds", "hold"],
}


def extract_keywords(query: str) -> list[str]:
    """Extract meaningful keywords from a natural language query.

    Returns 3-5 keywords ordered by likely importance.
    """
    # Lowercase and split
    words = re.findall(r'[a-zA-Z_][a-zA-Z0-9_.-]*', query.lower())

    # Remove stopwords
    meaningful = [w for w in words if w not in STOPWORDS]

    # If everything was stopwords, fall back to longest non-stopword-like words
    if not meaningful:
        meaningful = sorted(words, key=len, reverse=True)[:3]

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for w in meaningful:
        if w not in seen:
            seen.add(w)
            unique.append(w)

    # Cap at 5 keywords
    return unique[:5]


def expand_keywords(keywords: list[str]) -> list[str]:
    """Add domain-specific synonyms to keyword list.

    Returns expanded list (original keywords first, then synonyms).
    Capped at 8 total to avoid query explosion.
    """
    expanded = list(keywords)
    seen = set(k.lower() for k in keywords)

    for kw in keywords:
        for synonym in SYNONYMS.get(kw.lower(), []):
            if synonym.lower() not in seen:
                expanded.append(synonym)
                seen.add(synonym.lower())

    return expanded[:8]


def rewrite_query(query: str) -> dict:
    """Full pipeline: NL query → extracted keywords → expanded keywords.

    Returns:
        {
            "original": str,
            "keywords": list[str],       # extracted from NL
            "expanded": list[str],        # with synonyms added
            "fts_queries": list[str],     # ready for FTS5 MATCH
        }
    """
    keywords = extract_keywords(query)
    expanded = expand_keywords(keywords)

    # Build FTS5 queries — each keyword gets its own query
    # FTS5 MATCH uses double-quoted terms for exact matching
    fts_queries = [f'"{kw}"' for kw in expanded]

    return {
        "original": query,
        "keywords": keywords,
        "expanded": expanded,
        "fts_queries": fts_queries,
    }
```

---

## Task 2: Upgrade `engram_search` in MCP Server

**Modify:** `engram/mcp_server.py`

Replace the existing `engram_search` function. The key changes:
1. Import and use `rewrite_query`
2. Run FTS5 search for each expanded keyword
3. Merge, deduplicate, rank by relevance + recency
4. Return `query_interpreted_as` field

```python
# Replace the existing engram_search function with:

@server.tool()
def engram_search(
    query: str,
    limit: int = 10,
    project: str | None = None,
) -> str:
    """Search across all AI coding sessions. Returns matching messages with context.

    Args:
        query: Search terms (supports AND, OR, NOT, "exact phrases")
        limit: Max results to return (default 10)
        project: Filter to a specific project name
    """
    from engram.query_rewriter import rewrite_query

    db = _get_db()
    rewritten = rewrite_query(query)

    # Search each keyword independently, collect all results
    all_results: dict[tuple, dict] = {}  # (session_id, sequence) → result
    keyword_hits: dict[tuple, int] = {}  # (session_id, sequence) → hit count

    for fts_q in rewritten["fts_queries"]:
        try:
            results = db.search(fts_q, limit=limit * 3)  # oversample for merging
        except Exception:
            continue  # skip keywords that FTS5 rejects

        if project:
            results = [r for r in results if r.get("project") == project]

        for r in results:
            key = (r["session_id"], r.get("sequence", r.get("snippet", "")[:50]))
            if key not in all_results:
                all_results[key] = r
                keyword_hits[key] = 0
            keyword_hits[key] += 1

    if not all_results:
        return json.dumps({
            "results": [],
            "query_interpreted_as": rewritten["keywords"],
            "message": f"No results for: {query}",
        })

    # Rank: more keyword hits = more relevant, then by recency
    ranked = sorted(
        all_results.values(),
        key=lambda r: (
            keyword_hits[(r["session_id"], r.get("sequence", r.get("snippet", "")[:50]))],
            r.get("timestamp", ""),
        ),
        reverse=True,
    )

    output = []
    for r in ranked[:limit]:
        output.append({
            "session_id": r["session_id"],
            "project": r["project"],
            "role": r["role"],
            "tool_name": r["tool_name"],
            "snippet": r["snippet"],
            "timestamp": r["timestamp"],
        })

    return json.dumps({
        "results": output,
        "query_interpreted_as": rewritten["keywords"],
        "count": len(output),
    })
```

**Important:** Keep the existing `_sanitize_fts_query` function — it's still used internally by `db.search()`. The query rewriter generates pre-sanitized FTS5 queries so it bypasses that function.

---

## Task 3: Tests for Query Rewriter

**New file:** `tests/test_query_rewriter.py`

```python
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
```

---

## Verification

When done:

1. Run existing tests: `pytest tests/ -v` — all must pass (no regressions)
2. Run new tests: `pytest tests/test_query_rewriter.py -v`
3. Test MCP server manually:
   ```bash
   engram mcp  # starts the server
   ```
4. Verify NL search produces `query_interpreted_as`:
   ```python
   from engram.query_rewriter import rewrite_query
   print(rewrite_query("how did we configure hooks last time"))
   # Should show: keywords=["configure", "hooks"], expanded includes "settings", "config", etc.
   ```
5. `git add engram/query_rewriter.py engram/mcp_server.py tests/test_query_rewriter.py`
6. `git commit -m 'feat: NL query rewriting for engram_search MCP tool (Track 2)'`
7. Do NOT `git push`
