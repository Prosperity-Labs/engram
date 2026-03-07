# Engram Evolutionary Layer — Strategy Learning Architecture

## The Thesis

GRIP proved that AI agents can improve their own strategies over time.
Their approach: hand-crafted genome with fitness-based evolution.

Engram's approach: data-driven strategy learning from observed outcomes.
Same result, different method. GRIP defines strategies manually and 
evolves them. Engram discovers strategies from real session data and 
scores them empirically.

---

## What a "Strategy" Is

A strategy is a recorded approach to a task type. It's not code — 
it's a description of what worked.

```
Strategy:
  id:              "read_tests_first_bugfix"
  task_type:       "bug_fix"
  approach:        "Read test files before implementation files. 
                    Run failing test first to understand expected behavior."
  times_used:      12
  times_succeeded: 10
  fitness:         0.83
  avg_tokens:      45,000
  avg_duration:    8 min
  last_used:       2026-03-05
```

---

## The Strategies Table

```sql
CREATE TABLE strategies (
    id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,       -- bug_fix, feature, refactor, test, explore
    approach TEXT NOT NULL,        -- natural language description
    times_used INTEGER DEFAULT 0,
    times_succeeded INTEGER DEFAULT 0,
    fitness REAL DEFAULT 0.5,     -- succeeded / used
    avg_tokens REAL,
    avg_duration_seconds REAL,
    created_at DATETIME,
    last_used DATETIME,
    parent_id TEXT,               -- if this was mutated from another strategy
    FOREIGN KEY (parent_id) REFERENCES strategies(id)
);
```

Fitness decays daily for unused strategies.
New strategies start at 0.5 fitness (neutral).

---

## The Three Functions

### 1. Selection — Pick the Best Approach

When Loopwright gets a task, before spawning the agent:

```
Loopwright receives: "Fix the webhook validation bug"

Engram classifies: task_type = "bug_fix"

Engram queries strategies:
  1. "read_tests_first"     → fitness 0.83, used 12x
  2. "grep_for_error"       → fitness 0.71, used 8x
  3. "check_git_log"        → fitness 0.65, used 5x

Selection (80% exploit, 20% explore):
  → 80% chance: pick "read_tests_first" (highest fitness)
  → 20% chance: pick random (discover new approaches)

Inject into agent prompt:
  "Recommended approach: Read test files before implementation.
   Run failing test first to understand expected behavior.
   This approach succeeded in 10/12 past sessions."
```

### 2. Scoring — Measure the Outcome

After Loopwright finishes, Engram scores the run using artifact trail data:

```
Scoring dimensions:

  Success (50% weight):
    Did the task succeed? (git diff has changes + tests pass)
    1.0 = committed and tests pass
    0.5 = committed but no tests
    0.0 = no commit or tests fail

  Token efficiency (30% weight):
    Fewer tokens = better
    1.0 - min(actual_tokens / 500,000, 1.0)

  Exploration efficiency (20% weight):
    Lower exploration ratio = more efficient
    1.0 - min(reads / max(edits, 1) / 10, 1.0)

  Composite fitness:
    (success × 0.5) + (token_efficiency × 0.3) + (exploration × 0.2)
```

### 3. Mutation — Generate New Approaches

When a strategy's fitness drops below 0.3, generate a variant:

```
Base strategy: "grep for error message, then fix"
Fitness: 0.28 (failing)

Mutation modifiers:
  + "also check git log for recent changes to these files"
  + "read the test file before the implementation file"
  + "search engram for similar past tasks first"
  + "limit exploration to 5 file reads before first edit"
  + "check error logs before reading source code"

New strategy: "grep for error message, also check git log 
              for recent changes, then fix"
Parent: original strategy
Fitness: 0.5 (neutral, needs to prove itself)
```

Selection pressure does the rest. Better mutations survive.
Worse ones decay.

---

## The Full Loop

```
1. Task arrives
2. Loopwright asks Engram: "what task type? best strategy?"
3. Engram classifies and returns top strategy (80/20 explore/exploit)
4. Loopwright injects strategy into agent prompt
5. Agent executes
6. Engram records full artifact trail
7. Engram scores outcome → updates strategy fitness
8. If fitness < 0.3, generate mutation
9. Next similar task benefits from updated fitness scores
10. Repeat
```

---

## Connection to GRIP

GRIP's genome is hand-crafted evolutionary rules.
Engram's strategies are data-driven from observed outcomes.

```
GRIP:   Human defines strategies → System evolves via fitness
Engram: System observes sessions → Strategies emerge from data → Fitness scores from outcomes
```

Both achieve the same result: approaches that work get used more,
approaches that fail get retired. The difference is the source —
GRIP starts from human knowledge, Engram starts from data.

Over time these converge. Engram's data-driven strategies become 
as sophisticated as hand-crafted ones, but they're grounded in 
empirical evidence rather than assumptions.

---

## Connection to Nervous System

The evolutionary layer is how the nervous system LEARNS:

```
Sensory layer:     captures what happened
Knowledge graph:   structures it as relationships  
Reflex layer:      acts on it in real time
Evolutionary layer: improves the reflexes over time
```

The reflexes get better because the strategies they draw from
are continuously scored and evolved based on real outcomes.

---

## Connection to Knowledge Graph

Strategies are nodes in the graph:

```
Strategy → WORKS_FOR    → Concept   (bug_fix, refactor, etc.)
Strategy → USES_FILE    → File      (which files this approach touches)
Strategy → SUCCEEDS_IN  → Project   (which codebases it works for)
Strategy → CHILD_OF     → Strategy  (mutation lineage)
Error    → SOLVED_BY    → Strategy  (which approach fixes this error)
```

The graph enables strategy transfer: "This strategy works for 
webhook bugs in TypeScript projects" → apply to new TypeScript 
project with webhooks.

---

## Implementation Priority

1. Strategies table + basic fitness tracking (after artifact trail works)
2. Scoring from artifact trail data (after scorer built)
3. Selection integration with Loopwright (after Loopwright --print fixed)
4. Mutation system (after enough strategies have fitness data)
5. Knowledge graph integration (after graph in SQLite exists)

Total estimated code: ~400-500 lines across engram/strategies.py, 
engram/scorer.py, and loopwright/strategy_selector.ts
