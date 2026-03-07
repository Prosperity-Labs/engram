# Engram Simulation Engine — The Tenderly Equivalent

## Why Simulation Matters

Tenderly didn't just build a transaction viewer. They built their own EVM — 
a complete simulation environment where you can fork any state, change any 
parameter, and re-execute deterministically.

For Engram to be truly "Tenderly for AI agents," it needs the same capability:
fork a session at any point, inject different knowledge, and see what would 
have happened.

---

## The Core Challenge

Tenderly's EVM is deterministic: same input → same output. Always.

LLM agents are non-deterministic: same prompt → different output every time.

You can't replay an agent session and guarantee the same tool calls.
But you CAN control what the agent sees — the context is deterministic 
even if the LLM isn't.

```
TENDERLY'S EVM SIMULATION:
  State (storage) + Transaction (input) + EVM (engine) = Deterministic output

ENGRAM'S AGENT SIMULATION:
  Context (files, memory, knowledge) + Task (prompt) + LLM (engine) = Probabilistic output
  
  But the CONTEXT is deterministic and controllable.
  That's the simulation surface.
```

---

## Three Approaches

### Approach 1: Counterfactual Analysis (buildable now)

Don't re-run anything. Analyze existing session traces and calculate:
"If knowledge had been injected at tool call #N, which subsequent 
tool calls would have been unnecessary?"

```
Original session trace:
  #001 READ file_a.ts
  #002 READ file_b.ts
  #003 GREP "user_type" → 0 results
  #004 READ file_c.ts          ← unnecessary if we knew the answer
  #005 READ file_d.ts          ← unnecessary
  #006 READ file_e.ts          ← unnecessary
  #007 GLOB "*.ts" → 47 files  ← unnecessary
  #008 READ file_f.ts          ← unnecessary
  #009 Finally finds validators.ts
  #010 EDIT validators.ts

Counterfactual with knowledge injection at #003:
  #003 GREP "user_type" → 0 results
  #003.1 ENGRAM INJECTS: "validators.ts, endpoints.ts, schemas.ts, types.ts"
  #004 EDIT validators.ts (skips 5 unnecessary reads)

Estimated savings: 5 tool calls, ~3 minutes, ~$1.20
```

Zero token cost. Runs on historical data. Directionally correct.

### Approach 2: Statistical Simulation (month 2-3)

Actually re-run forked sessions with injected knowledge.
Run each scenario 5-10 times, average the results.

```
Fork session at tool call #3
Inject co-change knowledge
Re-run with real LLM 10 times

Results:
  8/10 runs: agent found right files in < 3 min
  2/10 runs: agent still explored (LLM non-determinism)
  Average savings: 4.2 tool calls, 2.8 minutes

Statistically valid. Expensive in tokens.
```

### Approach 3: The Engram VM (month 4+)

A lightweight simulation that doesn't use the LLM at all.
Models agent behavior as a state machine based on historical patterns.

```
Input:
  - Task description
  - Codebase state (file list, git state)
  - Knowledge artifacts available
  - Strategy selected

Simulation engine (ML model, not an LLM):
  - Predicts tool call sequence from historical patterns
  - Deterministic given same inputs
  - Trained on 500+ real sessions

Output:
  - Predicted tool sequence
  - Predicted cost
  - Predicted outcome probability
  - Files that would be touched
  - Estimated exploration ratio

Use cases:
  "If I inject this knowledge, how does the predicted session change?"
  "Which strategy produces the cheapest bug fix?"
  "Should I route this to Claude Code or Cursor?"
```

This is the real Tenderly equivalent — simulate cheaply without 
burning LLM tokens, then apply winning strategies to real sessions.

---

## Implementation Phases

```
Phase 1 (now):      Counterfactual analysis on existing traces
                    "What IF we had injected knowledge at step X?"
                    
Phase 2 (month 2):  Statistical simulation with real LLM
                    Validates whether interventions actually help
                    Expensive but empirically rigorous

Phase 3 (month 4):  Engram VM — lightweight behavior model
                    Trained on real session data
                    Tests intervention strategies in simulation
                    Fast, deterministic, zero LLM cost
                    
Phase 4 (month 6+): Full simulation environment
                    Fork any session at any point
                    Run in simulation or against real LLM
                    A/B test intervention strategies at scale
```

---

## Connection to Everything Else

The simulation engine validates the other layers:

- **Knowledge graph**: "Does injecting this subgraph actually help?"
- **Evolutionary layer**: "Does this strategy actually produce better outcomes?"
- **Reflex layer**: "Does this intervention fire at the right moment?"
- **ML models**: "Does the outcome predictor match real results?"

Without simulation, you're guessing. With simulation, you're measuring.
That's the Tenderly difference — not just observing, but testing 
counterfactuals.
