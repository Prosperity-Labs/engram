# Engram ML Roadmap — From Observability to Intelligence

## Vision

Engram evolves from a session observability tool into a learning system.
The progression: **observe → analyze → predict → optimize**.

Each phase builds on the previous. No phase requires the next to be useful.

---

## Phase 1: Data Foundation (Now — Pre-requisite for everything)

### Goal
Ensure every session captures the features needed for future ML training.

### Required Data Schema

Per session:
```
session_id          # unique identifier
task_description    # natural language (first user message)
task_type           # classified: bug_fix, feature, refactor, test, explore
tool_call_sequence  # ordered list of tool types
file_paths_touched  # ordered list of files read/written/edited
tokens_in           # input tokens
tokens_out          # output tokens
tokens_cache_read   # cache read tokens
tokens_cache_create # cache creation tokens
cost_estimate_usd   # computed from token counts
duration_seconds    # session duration
outcome             # success, partial, failure (from git commit + test results)
error_count         # bash failures (non-zero exit codes)
exploration_ratio   # reads / max(edits, 1)
file_diversity      # count of unique files touched
agent_type          # claude_code, cursor, codex (future)
```

Per tool call (artifact trail):
```
sequence            # order within session
timestamp_offset    # seconds from session start
tool_type           # READ, WRITE, EDIT, BASH, GLOB, GREP
file_path           # target file (if applicable)
old_content         # for edits: previous content
new_content         # for edits/writes: new content
command             # for bash: the command run
exit_code           # for bash: result code
content_size_tokens # approximate tokens in payload
tool_use_id         # for pairing request/response
is_error            # boolean
```

### Implementation
- Artifact trail (engram/artifact_trail.py) captures per-tool-call data
- Session-level features extracted during indexing
- Export command: `engram export --ml-features` → CSV, one row per session
- This CSV becomes the canonical training dataset

### Prompt for Claude Code
```
Add ML feature extraction to Engram's indexing pipeline.

When a session is indexed, compute and store these additional fields
in the sessions table:
- task_type: classify from first user message 
  (bug_fix, feature, refactor, test, explore, unknown)
- outcome: check if session ends with git commit + passing tests
  (success, partial, failure, unknown)  
- exploration_ratio: count of READ tool calls / max(EDIT+WRITE calls, 1)
- error_rate: count of bash calls with non-zero exit / total bash calls
- file_diversity: count of unique file paths in tool calls
- cost_estimate_usd: compute from token counts using Claude pricing

Add CLI command: engram export --ml-features -o sessions.csv
Exports one row per session with all ML-relevant columns.

Tests in tests/test_ml_features.py
```

---

## Phase 2: Classical ML (500-2,000 sessions)

### Goal
Build practical predictive models using traditional ML on current data.

### Models to Build

#### A. Session Outcome Predictor
- **Input:** First 10 tool calls of a session (types, file paths, exit codes)
- **Output:** Probability of success/failure
- **Model:** Random forest or gradient boosted trees
- **Value:** Early warning system — "this session is going badly, intervene"
- **Training data:** All sessions with known outcomes

#### B. Cost Estimator
- **Input:** Task description (TF-IDF or simple embeddings), task_type
- **Output:** Predicted token cost and duration
- **Model:** Linear regression or random forest
- **Value:** Before starting a task, estimate whether it'll cost $5 or $500
- **Training data:** All sessions with cost data

#### C. Session Behavior Clustering
- **Input:** Tool call distribution vector per session (% reads, % writes, % bash, etc.)
- **Output:** Cluster assignment (focused, exploratory, debugging, refactoring, etc.)
- **Model:** k-means or DBSCAN
- **Value:** Discover natural agent work modes; identify when agent is in wrong mode
- **Training data:** All sessions

#### D. Anomaly Detector
- **Input:** Running statistics during a session (read count, error rate, time since last edit)
- **Output:** Anomaly score (0-1)
- **Model:** Isolation forest or simple statistical bounds
- **Value:** "This session has read 30 files and made zero edits — top 2% exploration ratio"
- **Training data:** Historical session statistics as baseline

### Prompt for Claude Code
```
Build classical ML models for Engram session analysis.

Prerequisite: engram export --ml-features produces a clean CSV.

Create engram/ml/ directory with:

1. engram/ml/outcome_predictor.py
   - Train random forest on session features → outcome (success/failure)
   - Features: first 10 tool call types, early error rate, file diversity
   - Evaluate with cross-validation, report accuracy + F1
   - Save model to ~/.config/engram/models/

2. engram/ml/cost_estimator.py  
   - Train on task_type + file_diversity + historical avg → predicted cost
   - Evaluate with MAE (mean absolute error)

3. engram/ml/clustering.py
   - k-means on tool call distribution vectors
   - Find optimal k using elbow method
   - Label clusters by dominant characteristics
   - Visualize with t-SNE or PCA

4. engram/ml/anomaly.py
   - Isolation forest on session behavior features
   - Flag sessions above 95th percentile anomaly score

CLI commands:
  engram predict <task_description>  # cost + outcome prediction
  engram anomaly <session_id>        # anomaly score for running session

Dependencies: scikit-learn, pandas, numpy (no deep learning deps yet)
Tests in tests/test_ml_models.py
```

---

## Phase 3: Sequence Modeling (5,000-10,000 sessions)

### Goal
Learn the "grammar" of productive agent behavior from tool call sequences.

### Models to Build

#### A. Tool Call Language Model
- **Input:** Sequence of (tool_type, file_category, success/fail) tuples
- **Output:** Predicted next tool call
- **Model:** LSTM or small transformer (< 1M parameters)
- **Value:** Predict what the agent should do next; flag when it deviates from productive patterns
- **Training data:** Tool call sequences from all sessions, labeled by outcome

#### B. Strategy Embeddings
- **Input:** Full session as a sequence of tool calls
- **Output:** Fixed-size vector representing the session's "strategy"
- **Model:** Autoencoder on tool call sequences
- **Value:** Similar strategies cluster together; enables strategy-level search in Engram
  "Find sessions that used a similar approach to this one"

#### C. File Co-occurrence Model
- **Input:** Which files are touched together across sessions
- **Output:** File embeddings where related files are close in vector space
- **Model:** Word2Vec-style skip-gram on file paths (treating sessions as "sentences" and files as "words")
- **Value:** "You're editing validators.ts — you probably also need to edit schemas.ts and types.ts"
  Automatic file recommendations based on learned codebase structure

### Prerequisites
- Phase 1 data schema fully populated
- Phase 2 models validated and useful
- Multiple teams contributing session data (for generalization)
- PyTorch or TensorFlow added as optional dependency

---

## Phase 4: Transfer Learning & Foundation Model (100,000+ sessions)

### Goal
Build models that generalize across codebases, teams, and agent types.

### Models to Build

#### A. Agent Behavior Foundation Model
- **Input:** Task description + codebase metadata + tool call history
- **Output:** Optimal tool call sequence, predicted cost, predicted outcome
- **Model:** Small transformer (10-50M params) pre-trained on aggregate session data
- **Value:** A new team installs Engram and immediately gets predictions based on patterns learned from all other teams

#### B. Natural Language to Strategy
- **Input:** "Fix the auth bug in the signup flow"
- **Output:** Predicted file list, approach, estimated cost, estimated duration
- **Model:** Fine-tuned language model mapping task descriptions to session features
- **Value:** Before the agent starts, you know what it should do and what it'll cost

#### C. Cross-Agent Strategy Transfer
- **Input:** Session data from Claude Code, Cursor, Codex on same codebase
- **Output:** Per-agent strengths — "Claude Code is 40% cheaper for refactoring, Cursor is 2x faster for feature building"
- **Model:** Comparative analysis + recommendation model
- **Value:** Automatic agent routing — send each task to the best agent for that task type

### Prerequisites
- Multi-team, multi-agent data at scale
- Privacy-preserving aggregation (no code content leaves the team, only behavior patterns)
- Significant compute budget for training
- This phase likely requires VC funding or significant revenue

---

## Data Privacy Architecture

All ML training must respect data boundaries:

### What leaves the team (behavior patterns):
- Tool call types and sequences (READ, WRITE, EDIT, BASH)
- Timing and duration data
- File categories (not paths — e.g., "test file", "config", "API handler")
- Token counts and costs
- Success/failure outcomes
- Anonymized strategy descriptions

### What NEVER leaves the team:
- File contents or diffs
- Actual file paths (mapped to categories locally)
- Code snippets
- Conversation content
- API keys, credentials, environment variables
- Business logic or domain-specific code

### Implementation
- Local feature extraction runs on the team's machine
- Only the extracted feature vectors are synced
- Feature extraction is auditable — teams can inspect exactly what's shared
- Opt-in at every level: team can contribute to no ML, Phase 2 only, or full pipeline

---

## Integration with Evolutionary Layer

The ML models feed directly into Loopwright's strategy selection:

```
Phase 2 models → Better fitness scoring for strategies
Phase 3 models → Learned strategy embeddings replace manual strategy definitions  
Phase 4 models → Automatic strategy generation from task description
```

The evolutionary genome (strategies table) transitions from:
1. Hand-defined strategies with simple fitness scores (now)
2. ML-scored strategies with predicted outcomes (Phase 2)
3. Learned strategy embeddings with similarity search (Phase 3)
4. Auto-generated strategies from foundation model (Phase 4)

Each phase makes the system smarter without breaking the previous phase.

---

## Success Metrics Per Phase

| Phase | Metric | Target |
|-------|--------|--------|
| 1 | ML feature export works, clean CSV | 100% coverage |
| 2 | Outcome predictor accuracy | > 70% F1 |
| 2 | Cost estimator error | < 30% MAE |
| 2 | Anomaly detector catches real waste | > 50% precision |
| 3 | Next-tool-call prediction accuracy | > 60% |
| 3 | File recommendation relevance | > 70% hit rate |
| 4 | Cross-codebase transfer improves cold-start | > 30% improvement |

---

## Timeline Estimate

| Phase | Data Needed | Calendar Estimate |
|-------|-------------|-------------------|
| 1 — Data Foundation | Current (560+ sessions) | March 2026 |
| 2 — Classical ML | 1,000-2,000 sessions | April-May 2026 |
| 3 — Sequence Modeling | 5,000-10,000 sessions (multi-team) | Q3-Q4 2026 |
| 4 — Foundation Model | 100,000+ sessions | 2027+ |

Phase 1 and 2 are buildable solo. Phase 3 requires team adoption. Phase 4 requires funding.
