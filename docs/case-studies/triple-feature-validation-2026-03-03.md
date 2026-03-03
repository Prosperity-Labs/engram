# Case Study: Triple Feature Validation — Query Rewriter, Structured Brief, engram_recall

**Date:** 2026-03-03
**Context:** Experiment 004 on `feat/semantic-search` branch — validating three features that landed in commits `64de90d`, `fc0e4fa`, `24c01b6`

## Problem

Three features shipped back-to-back on the semantic search branch:
1. **Structured Brief** — 5-section `generate_brief()` (Intent, Decisions, Errors, Current State, Next Steps)
2. **Query Rewriter** — keyword extraction + synonym expansion for NL-to-FTS conversion
3. **engram_recall** — auto-recall MCP tool that detects when users reference past work

Prior experiments showed briefs cut planning time 55% (Exp 002) and NL search was 43% faster (Exp 003), but those tested older code. We needed to validate the new implementations work as well or better, and establish baselines for the new features (recall intent detection, structured sections, end-to-end recall pipeline).

## Approach

Built a single test file (`tests/test_experiment_004.py`) with 11 automated benchmarks spanning:
- **7 synthetic tests** (CI-safe, no real data needed) — keyword extraction, synonym expansion, recall intent precision/recall, topic keyword accuracy, rewriter latency
- **4 real-data tests** — rewritten vs raw FTS comparison, brief section quality scoring, recall end-to-end pipeline, brief generation latency

Each test has a target threshold and a stretch goal, grouped by feature for pass/fail decisions.

## Results

Every test passed. Every test hit the stretch target except Brief quality (8/10 vs 10/10 stretch).

### Scorecard

| # | Test | Target | Result |
|---|------|--------|--------|
| A | Keyword extraction accuracy | >=80% | **98%** (63/64) |
| B | Synonym expansion | >=75% | **100%** (8/8) |
| C1 | Recall intent recall | >=80% | **100%** (12/12) |
| C2 | Recall intent precision | >=90% | **100%** (8/8) |
| C3 | Topic keyword accuracy | >=70% | **100%** (22/22) |
| D | Rewritten >= Raw FTS | >=60% | **100%** (5/5) |
| E | Brief quality score | >=6/10 | **8/10** |
| F | Recall E2E accuracy | >=60% | **100%** (5/5) |
| G1 | Rewriter latency | <5ms | **0.004ms** |
| G2 | Brief latency | <2s | **0.466s** |

### Feature Verdicts

- **Query Rewriter**: PASS (A + B + C1 + C2 + G1)
- **Structured Brief**: PASS (E + G2)
- **engram_recall**: PASS (C3 + F)

## Key Findings

### 1. Raw NL queries fail completely in FTS5

Test D showed the starkest result: raw natural language queries like "How did we set up the JWT authentication?" return **zero results** from FTS5, while the rewritten query (extracting "jwt", "authentication", "set" and expanding to synonyms) returns 60 results. FTS5 doesn't understand stopwords or conversational phrasing — the rewriter is essential, not just nice-to-have.

### 2. Recall intent detection is precise

100% recall and 100% precision across 20 test phrases. The regex patterns in `_RECALL_PATTERNS` correctly distinguish "we already figured out X" (recall intent) from "please fix this error" (new task). Topic keyword extraction also scored 100%, meaning the captured group after the recall phrase reliably contains the searchable subject.

### 3. Brief quality varies by project richness

The "development" project scored 8/10 (strong Intent, Errors, Current State, Next Steps — but 0/2 on Decisions). The "monra-app/monra-core" project also scored 8/10 but with a different profile (strong Decisions, weak Next Steps). This suggests `_architecture_patterns()` keyword search is project-dependent — projects with explicit "chose", "because", "instead of" language in assistant messages score better.

### 4. Rewriter latency is negligible

At 0.004ms average (4 microseconds), the full `rewrite_query()` pipeline — regex tokenization, stopword filtering, deduplication, synonym expansion, FTS5 query building — adds zero perceptible overhead. This is 1,250x faster than the 5ms target.

### 5. Brief generation is fast even for large projects

0.466s for the richest project (365 sessions, 59K messages) — well under the 2s target and hitting the 0.5s stretch. The bottleneck is `_architecture_patterns()` which runs 10 FTS5 searches, but SQLite handles this efficiently.

## What Could Be Better

- **Brief Decisions section**: 2 of 3 projects scored 0/2 on Decisions. The keyword-based search for architecture decisions (`chose`, `decided`, `because`) is too dependent on the assistant using those exact words. Could improve with semantic search once that's wired for query-time encoding.
- **Recall E2E specificity**: Test F confirmed recall finds *something*, but the matched projects weren't always the engram project specifically (e.g., "vec0 INSERT OR REPLACE" matched monra-app, not engram). This is correct behavior (the fix was discussed in a monra-app session) but highlights that recall results need project-aware ranking.
- **Keyword cap at 5**: Test A's only miss was "middleware" being dropped because `extract_keywords()` caps at 5. The query "Fix the bug in API route validation middleware" extracted ["fix", "bug", "api", "route", "validation"] — all correct, but "middleware" was the 6th keyword. Could consider raising the cap or prioritizing longer/rarer words.

## Files

| File | Purpose |
|------|---------|
| `tests/test_experiment_004.py` | 11 automated benchmarks (7 synthetic + 4 real-data) |
| `docs/experiments/004-triple-feature-evaluation.md` | Full experiment protocol with manual A/B test and recall test templates |
| `engram/query_rewriter.py` | Tested: `extract_keywords()`, `expand_keywords()`, `detect_recall_intent()`, `rewrite_query()` |
| `engram/brief.py` | Tested: `generate_brief()`, `_session_intents()`, `_next_steps()`, `_architecture_patterns()` |

## Remaining Manual Tests

The experiment doc includes two manual A/B protocols still to execute:

- **Phase 2A**: `_architecture_patterns()` investigation — engram brief injected into CLAUDE.md vs cold start, isolated `/tmp` worktrees
- **Phase 2B**: Monra signup fix — real production bug (user_type/business_name not passed through createUser to Lambda). Measures turns to identify 4 target files, Lambda names, and discovery of unmerged branch work. Control (no engram) vs treatment (engram MCP enabled)
- **Phase 3**: 5 recall questions in a live session, scored 0-5 per question

See `docs/experiments/004-triple-feature-evaluation.md` for full protocols and results templates.

## Conclusion

All three features are validated and ready to ship. The query rewriter transforms unusable NL queries into effective FTS5 searches. The structured brief produces rich, scoreable output in under 500ms. The recall intent detector perfectly separates recall phrases from new tasks. Next step: merge `feat/semantic-search` to main, then run the manual A/B and recall tests (Phases 2A, 2B, and 3 of Experiment 004).
