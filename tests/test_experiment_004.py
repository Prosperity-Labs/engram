"""Experiment 004: Structured Brief + Query Rewriter + Recall Evaluation.

Automated benchmarks for three features:
  1. Query Rewriter — keyword extraction, synonym expansion, recall intent
  2. Structured Brief — 5-section generate_brief() quality scoring
  3. engram_recall — end-to-end recall from past sessions

Runs against REAL data when ~/.config/engram/sessions.db exists.
Synthetic tests (A, B, C) run in any environment (CI-safe).
"""

from __future__ import annotations

import os
import time

import pytest

from engram.query_rewriter import (
    detect_recall_intent,
    expand_keywords,
    extract_keywords,
    rewrite_query,
)

REAL_DB = os.path.expanduser("~/.config/engram/sessions.db")
HAS_REAL_DATA = os.path.exists(REAL_DB)


# ── A) Keyword Extraction Accuracy ──────────────────────────────────

KEYWORD_TEST_CASES: list[dict] = [
    {
        "query": "How do I set up JWT authentication in the login handler?",
        "must_include": ["jwt", "authentication", "login"],
        "must_not_include": ["how", "do", "i", "the", "in"],
    },
    {
        "query": "What was the Docker deployment configuration we used?",
        "must_include": ["docker", "deployment", "configuration"],
        "must_not_include": ["what", "was", "the", "we"],
    },
    {
        "query": "Find the database migration script for PostgreSQL",
        "must_include": ["database", "migration", "postgresql"],
        "must_not_include": ["find", "the", "for"],
    },
    {
        "query": "Show me the webhook endpoint error handling",
        "must_include": ["webhook", "endpoint", "error"],
        "must_not_include": ["show", "me", "the"],
    },
    {
        "query": "Where is the config file for test settings?",
        "must_include": ["config"],
        "must_not_include": ["where", "is", "the", "for"],
    },
    {
        "query": "The escrow deposit function broke after the refactor",
        "must_include": ["escrow", "deposit", "broke", "refactor"],
        "must_not_include": ["the", "after"],
    },
    {
        "query": "Fix the bug in API route validation middleware",
        "must_include": ["api", "route", "validation", "middleware"],
        "must_not_include": ["the", "in"],
    },
    {
        "query": "How did we configure the CI pipeline for staging?",
        "must_include": ["configure", "pipeline", "staging"],
        "must_not_include": ["how", "did", "we", "the", "for"],
    },
    {
        "query": "Update the session token refresh logic",
        "must_include": ["session", "token", "refresh", "logic"],
        "must_not_include": ["the"],
    },
    {
        "query": "Debug the failing pytest hooks in pre-commit",
        "must_include": ["debug", "failing", "pytest", "hooks", "pre-commit"],
        "must_not_include": ["the", "in"],
    },
]


def test_a_keyword_extraction_accuracy():
    """A) Keyword extraction: >=80% accuracy across 10 NL queries."""
    total_checks = 0
    passed_checks = 0

    print("\n--- A) Keyword Extraction Accuracy ---")

    for case in KEYWORD_TEST_CASES:
        keywords = extract_keywords(case["query"])
        kw_lower = {k.lower() for k in keywords}

        for must in case["must_include"]:
            total_checks += 1
            if must.lower() in kw_lower:
                passed_checks += 1
            else:
                print(f"  MISS: '{must}' not in {keywords} for: {case['query'][:60]}")

        for must_not in case["must_not_include"]:
            total_checks += 1
            if must_not.lower() not in kw_lower:
                passed_checks += 1
            else:
                print(f"  LEAK: '{must_not}' found in {keywords} for: {case['query'][:60]}")

    accuracy = passed_checks / total_checks if total_checks else 0
    print(f"\nKeyword accuracy: {accuracy:.0%} ({passed_checks}/{total_checks})")
    print(f"Target: >=80%  |  Result: {'PASS' if accuracy >= 0.80 else 'FAIL'}")

    assert accuracy >= 0.80, f"Keyword extraction accuracy {accuracy:.0%} < 80%"


# ── B) Synonym Expansion ────────────────────────────────────────────

SYNONYM_TEST_CASES: list[dict] = [
    {"keywords": ["auth"], "expected_any": ["authentication", "login", "JWT", "token"]},
    {"keywords": ["hook"], "expected_any": ["hooks", "PreToolUse", "PostToolUse"]},
    {"keywords": ["config"], "expected_any": ["configuration", "settings", "setup"]},
    {"keywords": ["error"], "expected_any": ["bug", "fix", "fail", "broken"]},
    {"keywords": ["test"], "expected_any": ["tests", "testing", "pytest", "jest"]},
    {"keywords": ["deploy"], "expected_any": ["deployment", "CI", "CD", "pipeline"]},
    {"keywords": ["database"], "expected_any": ["db", "SQL", "SQLite", "schema"]},
    {"keywords": ["api"], "expected_any": ["endpoint", "route", "REST", "webhook"]},
]


def test_b_synonym_expansion():
    """B) Synonym expansion: >=75% of keyword sets get at least 1 correct synonym."""
    hits = 0

    print("\n--- B) Synonym Expansion ---")

    for case in SYNONYM_TEST_CASES:
        expanded = expand_keywords(case["keywords"])
        expanded_lower = {e.lower() for e in expanded}
        found = [s for s in case["expected_any"] if s.lower() in expanded_lower]

        if found:
            hits += 1
            print(f"  {case['keywords']} -> found: {found}")
        else:
            print(f"  MISS: {case['keywords']} -> {expanded}, expected any of {case['expected_any']}")

    accuracy = hits / len(SYNONYM_TEST_CASES) if SYNONYM_TEST_CASES else 0
    print(f"\nSynonym accuracy: {accuracy:.0%} ({hits}/{len(SYNONYM_TEST_CASES)})")
    print(f"Target: >=75%  |  Result: {'PASS' if accuracy >= 0.75 else 'FAIL'}")

    assert accuracy >= 0.75, f"Synonym expansion {accuracy:.0%} < 75%"


# ── C) Recall Intent Precision/Recall ────────────────────────────────

RECALL_POSITIVE = [
    {"text": "We already figured out the JWT auth flow", "topic_must_include": ["jwt", "auth"]},
    {"text": "How did we fix the database migration?", "topic_must_include": ["database", "migration"]},
    {"text": "What was the command for deploying to staging?", "topic_must_include": ["deploying", "staging"]},
    {"text": "Remember when we set up the Docker config?", "topic_must_include": ["docker", "config"]},
    {"text": "We've done this before: webhook endpoint setup", "topic_must_include": ["webhook", "endpoint"]},
    {"text": "Last time we configured the CI pipeline", "topic_must_include": ["configured", "pipeline"]},
    {"text": "Didn't we already solve the escrow deposit bug?", "topic_must_include": ["escrow"]},
    {"text": "We previously handled the token refresh issue", "topic_must_include": ["token", "refresh"]},
    {"text": "How did I configure the test hooks?", "topic_must_include": ["hooks"]},
    {"text": "What was the approach for the API rate limiting?", "topic_must_include": ["api", "rate"]},
    {"text": "Wasn't there a solution for the login redirect?", "topic_must_include": ["login", "redirect"]},
    {"text": "We worked out the nginx proxy settings", "topic_must_include": ["nginx", "proxy"]},
]

RECALL_NEGATIVE = [
    "Can you help me write a new function?",
    "Please fix this TypeScript error",
    "Add a button to the settings page",
    "What does this error message mean?",
    "Refactor the auth module to use classes",
    "Run the test suite and show me failures",
    "Create a new migration for the users table",
    "Explain how React hooks work",
]


def test_c_recall_intent_recall():
    """C1) Recall intent recall: >=80% of positive phrases detected."""
    detected = 0

    print("\n--- C1) Recall Intent Recall ---")

    for case in RECALL_POSITIVE:
        result = detect_recall_intent(case["text"])
        if result is not None:
            detected += 1
            print(f"  HIT: '{case['text'][:50]}' -> topic='{result['topic'][:40]}'")
        else:
            print(f"  MISS: '{case['text'][:50]}' -> None")

    recall = detected / len(RECALL_POSITIVE) if RECALL_POSITIVE else 0
    print(f"\nRecall: {recall:.0%} ({detected}/{len(RECALL_POSITIVE)})")
    print(f"Target: >=80%  |  Result: {'PASS' if recall >= 0.80 else 'FAIL'}")

    assert recall >= 0.80, f"Recall intent recall {recall:.0%} < 80%"


def test_c_recall_intent_precision():
    """C2) Recall intent precision: >=90% of negative phrases correctly rejected."""
    rejected = 0

    print("\n--- C2) Recall Intent Precision ---")

    for text in RECALL_NEGATIVE:
        result = detect_recall_intent(text)
        if result is None:
            rejected += 1
            print(f"  OK: '{text[:50]}' -> None")
        else:
            print(f"  FALSE POS: '{text[:50]}' -> {result['match'][:40]}")

    precision = rejected / len(RECALL_NEGATIVE) if RECALL_NEGATIVE else 0
    print(f"\nPrecision: {precision:.0%} ({rejected}/{len(RECALL_NEGATIVE)})")
    print(f"Target: >=90%  |  Result: {'PASS' if precision >= 0.90 else 'FAIL'}")

    assert precision >= 0.90, f"Recall intent precision {precision:.0%} < 90%"


def test_c_recall_topic_keyword_accuracy():
    """C3) Topic keyword accuracy: >=70% of detected topics contain expected keywords."""
    total_checks = 0
    passed_checks = 0

    print("\n--- C3) Recall Topic Keyword Accuracy ---")

    for case in RECALL_POSITIVE:
        result = detect_recall_intent(case["text"])
        if result is None:
            # Missed detection — count all expected keywords as failures
            total_checks += len(case["topic_must_include"])
            continue

        kw_lower = {k.lower() for k in result["keywords"]}
        topic_lower = result["topic"].lower()

        for expected in case["topic_must_include"]:
            total_checks += 1
            # Check if keyword appears in extracted keywords OR in topic text
            if expected.lower() in kw_lower or expected.lower() in topic_lower:
                passed_checks += 1
            else:
                print(
                    f"  MISS: '{expected}' not in keywords={result['keywords']} "
                    f"or topic='{result['topic'][:40]}' for: {case['text'][:50]}"
                )

    accuracy = passed_checks / total_checks if total_checks else 0
    print(f"\nTopic keyword accuracy: {accuracy:.0%} ({passed_checks}/{total_checks})")
    print(f"Target: >=70%  |  Result: {'PASS' if accuracy >= 0.70 else 'FAIL'}")

    assert accuracy >= 0.70, f"Topic keyword accuracy {accuracy:.0%} < 70%"


# ── D) Rewritten vs Raw FTS (real data) ─────────────────────────────

NL_QUERIES_FOR_FTS = [
    "How did we set up the JWT authentication?",
    "What was the Docker deployment process?",
    "Show me the database migration approach",
    "Find where we configured the webhook endpoints",
    "What errors did we hit with the test suite?",
]


@pytest.mark.skipif(not HAS_REAL_DATA, reason="No real session data")
def test_d_rewritten_vs_raw_fts_real_data():
    """D) Rewritten query gets >= raw results in >=60% of queries."""
    from engram.recall.session_db import SessionDB

    db = SessionDB(REAL_DB)
    rewritten_wins = 0

    print("\n--- D) Rewritten vs Raw FTS (REAL DATA) ---")

    for query in NL_QUERIES_FOR_FTS:
        rewritten = rewrite_query(query)

        # Raw: use the original NL query directly in FTS
        try:
            raw_results = db.search(query, limit=10)
        except Exception:
            raw_results = []

        # Rewritten: search each expanded keyword, merge unique results
        rewritten_results = []
        seen_ids = set()
        for fts_q in rewritten["fts_queries"]:
            try:
                results = db.search(fts_q, limit=10)
            except Exception:
                continue
            for r in results:
                key = (r["session_id"], r.get("sequence", 0))
                if key not in seen_ids:
                    seen_ids.add(key)
                    rewritten_results.append(r)

        raw_count = len(raw_results)
        rewritten_count = len(rewritten_results)

        if rewritten_count >= raw_count:
            rewritten_wins += 1

        status = "WIN" if rewritten_count >= raw_count else "LOSE"
        print(
            f"  '{query[:45]}': raw={raw_count}, rewritten={rewritten_count} [{status}]"
        )

    win_rate = rewritten_wins / len(NL_QUERIES_FOR_FTS) if NL_QUERIES_FOR_FTS else 0
    print(f"\nRewritten win rate: {win_rate:.0%} ({rewritten_wins}/{len(NL_QUERIES_FOR_FTS)})")
    print(f"Target: >=60%  |  Result: {'PASS' if win_rate >= 0.60 else 'FAIL'}")

    assert win_rate >= 0.60, f"Rewritten win rate {win_rate:.0%} < 60%"


# ── E) Brief Section Quality (real data) ─────────────────────────────


def _score_brief_sections(brief_text: str) -> dict:
    """Score each section of a structured brief on a 0-2 scale.

    Rubric:
      Intent:        0 = missing, 1 = present but trivial, 2 = content + non-trivial
      Decisions:     0 = missing, 1 = present, 2 = present + no boilerplate
      Errors:        0 = missing, 1 = "None" only, 2 = has recurring errors
      Current State: 0 = missing, 1 = stats only, 2 = stats + files listed
      Next Steps:    0 = missing, 1 = generic, 2 = forward-looking text
    """
    scores: dict[str, int] = {}

    # Intent
    if "## Intent" in brief_text:
        intent_section = brief_text.split("## Intent")[1].split("## ")[0]
        lines = [l.strip() for l in intent_section.strip().splitlines() if l.strip().startswith("- ")]
        if not lines or lines == ["- No session data available"]:
            scores["intent"] = 0
        elif any(len(l) > 30 for l in lines):
            scores["intent"] = 2
        else:
            scores["intent"] = 1
    else:
        scores["intent"] = 0

    # Decisions
    if "## Decisions" in brief_text:
        decisions_section = brief_text.split("## Decisions")[1].split("## ")[0]
        lines = [l.strip() for l in decisions_section.strip().splitlines() if l.strip().startswith("- ")]
        if not lines or lines == ["- None"]:
            scores["decisions"] = 0
        elif any(len(l) > 60 for l in lines):
            scores["decisions"] = 2
        else:
            scores["decisions"] = 1
    else:
        scores["decisions"] = 0

    # Errors
    if "## Errors" in brief_text:
        errors_section = brief_text.split("## Errors")[1].split("## ")[0]
        lines = [l.strip() for l in errors_section.strip().splitlines() if l.strip().startswith("- ")]
        if not lines or lines == ["- None"]:
            scores["errors"] = 1  # "None" is valid — some projects have no errors
        elif any("occurrences" in l or "sessions" in l for l in lines):
            scores["errors"] = 2
        else:
            scores["errors"] = 1
    else:
        scores["errors"] = 0

    # Current State
    if "## Current State" in brief_text:
        state_section = brief_text.split("## Current State")[1].split("## Next")[0]
        has_stats = "Sessions:" in state_section or "Messages:" in state_section
        has_files = "Most Modified" in state_section or "Most Read" in state_section
        if has_stats and has_files:
            scores["current_state"] = 2
        elif has_stats or has_files:
            scores["current_state"] = 1
        else:
            scores["current_state"] = 0
    else:
        scores["current_state"] = 0

    # Next Steps
    if "## Next Steps" in brief_text:
        next_section = brief_text.split("## Next Steps")[1]
        lines = [l.strip() for l in next_section.strip().splitlines() if l.strip().startswith("- ")]
        if not lines or lines == ["- No forward-looking statements found in recent sessions"]:
            scores["next_steps"] = 0
        elif any(len(l) > 30 for l in lines):
            scores["next_steps"] = 2
        else:
            scores["next_steps"] = 1
    else:
        scores["next_steps"] = 0

    scores["total"] = sum(scores.values())
    return scores


@pytest.mark.skipif(not HAS_REAL_DATA, reason="No real session data")
def test_e_brief_section_quality_real_data():
    """E) Brief quality: >=6/10 for richest project."""
    from engram.brief import generate_brief
    from engram.recall.session_db import SessionDB

    db = SessionDB(REAL_DB)

    # Find top 3 projects by session count
    with db._connect() as conn:
        rows = conn.execute(
            """SELECT project, COUNT(*) as cnt FROM sessions
               WHERE project IS NOT NULL
               GROUP BY project ORDER BY cnt DESC LIMIT 3"""
        ).fetchall()

    assert rows, "No projects found"

    print("\n--- E) Brief Section Quality (REAL DATA) ---")

    best_score = 0
    best_project = None

    for row in rows:
        project = row["project"]
        brief = generate_brief(db, project, format="markdown")

        scores = _score_brief_sections(brief)
        total = scores["total"]

        print(f"\n  Project: {project}")
        print(f"    Intent:        {scores['intent']}/2")
        print(f"    Decisions:     {scores['decisions']}/2")
        print(f"    Errors:        {scores['errors']}/2")
        print(f"    Current State: {scores['current_state']}/2")
        print(f"    Next Steps:    {scores['next_steps']}/2")
        print(f"    TOTAL:         {total}/10")

        if total > best_score:
            best_score = total
            best_project = project

    print(f"\nBest project: {best_project} with {best_score}/10")
    print(f"Target: >=6/10  |  Result: {'PASS' if best_score >= 6 else 'FAIL'}")

    assert best_score >= 6, f"Best brief score {best_score}/10 < 6/10"


# ── F) Recall End-to-End (real data) ─────────────────────────────────

RECALL_E2E_PHRASES = [
    "How did we set up the semantic search embeddings?",
    "What was the command for batch embedding with OpenAI?",
    "Remember when we fixed the vec0 INSERT OR REPLACE issue?",
    "We already figured out the sqlite-vec KNN query syntax",
    "Didn't we already solve the ONNX model loading?",
]


@pytest.mark.skipif(not HAS_REAL_DATA, reason="No real session data")
def test_f_recall_e2e_real_data():
    """F) Recall E2E: >=60% of recall phrases find a relevant session."""
    from engram.recall.session_db import SessionDB

    db = SessionDB(REAL_DB)
    hits = 0

    print("\n--- F) Recall End-to-End (REAL DATA) ---")

    for phrase in RECALL_E2E_PHRASES:
        # Step 1: Detect recall intent and extract keywords
        intent = detect_recall_intent(phrase)
        if intent is None:
            # Fallback: just extract keywords directly
            keywords = extract_keywords(phrase)
        else:
            keywords = intent["keywords"]

        # Step 2: Search with extracted keywords
        found_any = False
        for kw in keywords[:3]:
            try:
                results = db.search(f'"{kw}"', limit=5)
            except Exception:
                continue
            if results:
                found_any = True
                projects = {r.get("project", "?") for r in results[:3]}
                print(f"  HIT: '{phrase[:50]}' -> kw='{kw}' -> projects={projects}")
                break

        if found_any:
            hits += 1
        else:
            print(f"  MISS: '{phrase[:50]}' -> keywords={keywords}")

    accuracy = hits / len(RECALL_E2E_PHRASES) if RECALL_E2E_PHRASES else 0
    print(f"\nRecall E2E accuracy: {accuracy:.0%} ({hits}/{len(RECALL_E2E_PHRASES)})")
    print(f"Target: >=60%  |  Result: {'PASS' if accuracy >= 0.60 else 'FAIL'}")

    assert accuracy >= 0.60, f"Recall E2E accuracy {accuracy:.0%} < 60%"


# ── G) Latency Benchmarks ───────────────────────────────────────────

LATENCY_QUERIES = [
    "How did we set up the JWT authentication?",
    "Find the database migration for users table",
    "What was the Docker deployment config?",
    "Show me the webhook error handling",
    "Where is the test configuration file?",
]


def test_g1_rewriter_latency():
    """G1) rewrite_query latency: <5ms average."""
    times = []

    print("\n--- G1) Rewriter Latency ---")

    for query in LATENCY_QUERIES:
        start = time.perf_counter()
        for _ in range(100):  # 100 iterations for stable measurement
            rewrite_query(query)
        elapsed = (time.perf_counter() - start) / 100

        times.append(elapsed)
        print(f"  '{query[:40]}': {elapsed*1000:.3f}ms")

    avg_ms = (sum(times) / len(times)) * 1000
    print(f"\nAverage rewrite latency: {avg_ms:.3f}ms")
    print(f"Target: <5ms  |  Result: {'PASS' if avg_ms < 5 else 'FAIL'}")

    assert avg_ms < 5, f"Rewrite latency {avg_ms:.1f}ms >= 5ms"


@pytest.mark.skipif(not HAS_REAL_DATA, reason="No real session data")
def test_g2_brief_latency_real_data():
    """G2) generate_brief latency: <2s for real projects."""
    from engram.brief import generate_brief
    from engram.recall.session_db import SessionDB

    db = SessionDB(REAL_DB)

    # Find the richest project
    with db._connect() as conn:
        row = conn.execute(
            """SELECT project FROM sessions
               WHERE project IS NOT NULL
               GROUP BY project ORDER BY COUNT(*) DESC LIMIT 1"""
        ).fetchone()

    assert row, "No projects found"
    project = row["project"]

    print(f"\n--- G2) Brief Latency (project: {project}) ---")

    times = []
    for i in range(3):
        start = time.perf_counter()
        generate_brief(db, project, format="markdown")
        elapsed = time.perf_counter() - start
        times.append(elapsed)
        print(f"  Run {i+1}: {elapsed:.3f}s")

    avg_s = sum(times) / len(times)
    print(f"\nAverage brief latency: {avg_s:.3f}s")
    print(f"Target: <2s  |  Result: {'PASS' if avg_s < 2 else 'FAIL'}")

    assert avg_s < 2, f"Brief latency {avg_s:.1f}s >= 2s"


# ── Scorecard Summary ────────────────────────────────────────────────

def test_scorecard_summary():
    """Print the scorecard summary (always runs, reports synthetic-only results)."""
    print("\n" + "=" * 60)
    print("EXPERIMENT 004 SCORECARD (synthetic tests only)")
    print("=" * 60)
    print("Run with real data for full scorecard:")
    print("  uv run pytest tests/test_experiment_004.py -v -s -k real_data")
    print("=" * 60)
