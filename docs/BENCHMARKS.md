# Engram Benchmarks

Real data results from `~/.config/engram/sessions.db` (13,881 artifacts, 180+ sessions).
Synthetic fallback runs in CI via `tmp_db` fixtures.

## Scorecard

| Benchmark | Score | Target | Status |
|---|---|---|---|
| Artifact Completeness | 89.1% | >80% | PASS |
| Context Recovery | 100% | >60% | PASS |
| Token Savings | 64% | >50% | PASS |
| Search Precision | 89% | >70% | PASS |

## What Each Benchmark Measures

### Artifact Completeness (89.1%)

Of all assistant messages with `tool_name` set, how many produced a structured artifact?

- **11,957 / 13,424** tool calls captured
- Gap: Claude Code meta-tools the extractor doesn't handle yet:
  - TaskUpdate (353), Task (202), TaskCreate (183)
  - WebFetch (132), TodoWrite (99)
- These are trackable but low-value — the 89.1% covers the tools that matter (Read, Edit, Write, Bash, Grep, Glob).

### Context Recovery (100%)

Can Engram's stored data answer 7 basic project questions?

1. Session count recoverable
2. Modified files tracked
3. Errors captured
4. Tool usage stats available
5. Topic search works
6. File read history exists
7. Commands tracked

Tested against top 5 real projects (by artifact count). All 35/35 checks passed.

### Token Savings (64%)

What % of redundant file re-reads would `engram brief` preempt by listing key files upfront?

- **monra-app**: 1,016 total reads, 335 redundant (33%), brief preempts 213 (64%)
- Global: 868/3,621 reads redundant (24% of all reads across all projects)
- The brief's "Key Files" section lists the 14 most-read and most-modified files. An agent that sees this list can skip re-reading files it already knows about.

### Search Precision (89%)

For each project, can FTS5 search find content from that project using a distinctive term?

- Strategy: extract distinctive single words from artifact targets (file names), search as unquoted terms
- 8/9 projects found on first or second candidate query
- Key finding: FTS5 tokenizes on hyphens/underscores, so single words (`TransactionLifecycleService`) work better than quoted phrases (`"management-service"`)

## Running Benchmarks

```bash
# All benchmarks (synthetic + real data if available)
pytest tests/test_benchmark_*.py -v -s

# Scorecard view
python benchmark/run_benchmarks.py

# Single benchmark
pytest tests/test_benchmark_tokens.py -v -s
```

Real data tests are skipped automatically in CI when `~/.config/engram/sessions.db` doesn't exist.
