# Engram — Session Summary & Direction
## March 5-6, 2026 (Marathon Session)

---

## Documents Produced

Store these in `docs/architecture/` in the Engram repo:

1. **engram-proxy-architecture.md** — The Nervous System Vision
   - Full proxy layer design (sensory → integration → reflex)
   - Five intervention types (OBSERVE, AUGMENT, WARN, REDIRECT, BLOCK)
   - Four implementation approaches (CLAUDE.md → Smart MCP → Shadow → Wrapper)
   - Simulated before/after on Monra signup fix
   - Cross-agent nervous system architecture
   - Compound effect over time (1 → 500 → 5,000 sessions)

2. **engram-ml-roadmap.md** — From Observability to Intelligence
   - Phase 1: Data foundation (feature schema for ML training)
   - Phase 2: Classical ML (outcome predictor, cost estimator, clustering, anomaly detection)
   - Phase 3: Sequence modeling (tool call language model, strategy embeddings)
   - Phase 4: Foundation model (cross-codebase transfer learning)
   - Privacy architecture for aggregate data
   - Integration with evolutionary layer

3. **engram-knowledge-reuse-roadmap.md** — Research Memory System
   - Six knowledge artifact types (competitive, technical, market, architecture, conversation, experiment)
   - Capture, retrieval, and freshness/refresh workflows
   - Integration with proxy reflexes for auto-surfacing
   - CLI commands for knowledge management

4. **engram-knowledge-graph-architecture.md** — Context Compression via Graph
   - Why bigger context windows fail (GPT-5.4 accuracy data)
   - Graph as compression algorithm for experience
   - Three functions: Navigate, Remember, Predict
   - Three-tier context: HOT (<4K) → WARM (<32K) → COLD (in DB)
   - Node and edge type taxonomy
   - Flow reusability (replayable successful sequences)
   - SQLite-first implementation, Memgraph later

5. **engram-evolutionary-layer.md** — Strategy Learning Architecture
   - Strategies table with fitness scoring
   - Selection (80/20 exploit/explore)
   - Scoring from artifact trail (success, token efficiency, exploration ratio)
   - Mutation via approach modifiers
   - Connection to GRIP's genome (data-driven vs hand-crafted)
   - Integration with Loopwright execution loop

6. **engram-simulation-engine.md** — The Tenderly Equivalent
   - Why agent simulation is harder than EVM simulation (non-deterministic)
   - Three approaches: counterfactual analysis → statistical simulation → Engram VM
   - The Engram VM: lightweight behavior model, deterministic, zero LLM cost
   - Validates knowledge graph, evolutionary layer, and reflex system

7. **engram-self-funding-model.md** — Sustainability & Open Infrastructure
   - Self-funding compounding loop (Accenture supply chain research applied)
   - Revenue streams by timeline (consulting → managed hosting → enterprise)
   - Open infrastructure thesis (Linux model, not Datadog model)
   - Task audit framework (frequency × complexity 2×2)
   - March 2026 goal: first paid contract

---

## Architecture Decisions Made

### The Nervous System Metaphor (North Star)
- Engram is the nervous system, not the brain
- It senses (observes tool calls), transmits (surfaces knowledge), and fires reflexes (interventions)
- Agent-agnostic: works with any agent, any model
- The metaphor holds from solo developer to enterprise scale

### Knowledge Graph > Flat Context
- Bigger context windows don't help (GPT-5.4: 97% at 16K → 36% at 512K)
- Knowledge graph compresses experience into relationships
- Inject 200 tokens of structured relationships, not 200K tokens of raw history
- Three-tier: HOT (<4K, in prompt) → WARM (<32K, via MCP) → COLD (in DB, on demand)
- Start with graph-in-SQLite (nodes + edges tables), migrate to Memgraph later

### Evolutionary Layer Design
- Strategies table in SQLite with fitness scores
- Explore/exploit selection (80/20)
- Scoring from artifact trail data (success, token efficiency, exploration ratio)
- Mutation via approach modifiers
- Connection: Loopwright executes → Engram records → scores update → better selection

### Self-Funding Model (from Accenture supply chain research)
- Each phase generates value that funds the next phase
- Phase 1: CLAUDE.md generator → saves time → time builds Phase 2
- MCP consulting revenue funds Engram development
- No big bang transformation needed — compounding returns

---

## Competitive Landscape (as of March 2026)

| Tool | What It Is | Overlap with Engram |
|------|-----------|-------------------|
| GRIP | Self-improving AI OS with genome/fitness evolution | Memory + evolution (different: single-agent OS vs cross-agent nervous system) |
| Tastematter | Session indexer with co-access queries and file heat | Session indexing (lighter version of what Engram already does, no graph) |
| claude-spend | Cost visibility dashboard, npx one-command | Cost analytics only (subset of Engram, 200+ users, viral) |
| Codified Context | Three-tier memory for 108K-line C# system | Memory architecture (paper, not a tool) |
| Open Brain | Cross-tool memory via Postgres + MCP | Cross-agent memory (similar thesis, different implementation) |
| Anthropic Auto Memory | Native CLAUDE.md + MEMORY.md in Claude Code | Session memory (platform feature, can't compete directly) |
| noodlbox | .git for context, code context retrieval | Complementary, not competing |

### Key Differentiators for Engram
- **Cross-agent observability** — nobody else tracks Claude Code + Cursor + Codex unified
- **Artifact trail with state diffs** — nobody tracks file-level changes per tool call
- **Real-time intervention (reflexes)** — nobody does mid-session intelligent interrupts
- **Behavioral analytics from data** — exploration ratios, co-change patterns, danger zones
- **Evolutionary learning** — data-driven, not hand-crafted like GRIP's genome

---

## Data Snapshot (from interrogation)

- 418 sessions, 65,981 messages, 20,700 tool calls, 73 projects, 69 days
- $1,245 spent (Sonnet), $4,031 saved by caching (76%)
- Most expensive session: $154 (OpenClaw)
- Median session cost: $0.82
- Avg exploration ratio: 3.15:1 (worst: 27:1)
- Most-read file: handlers.ts (182 times across 22 sessions)
- Top co-change: validators.ts ↔ endpoints.ts (6x)
- 44% of sessions < 30 min, 15% > 8 hours

---

## GRIP Founder Call Insights (March 5)

- Recursive self-improvement is real engineering, not branding
- Genome/fitness model with actual evolutionary optimization
- "Delight Metric" emerged spontaneously from RSI loop
- Founder renamed ai_delight → system_health (philosophical discipline)
- GRIP = operating system, Engram = nervous system (complementary, not competing)
- Potential collaboration worth exploring after Engram dashboard exists
- Based in South Africa (CodeTonight/ENTER Konsult)

---

## Open Source Models + Agent Loops

- Claude Code works with open source models via LiteLLM proxy
- Set ANTHROPIC_BASE_URL to redirect to Ollama, LM Studio, llama.cpp
- Qwen3 Coder, Devstral, DeepSeek all work
- OpenCode (112K GitHub stars) is open source alternative with any-model support
- Engram's proxy layer is model-agnostic by design — watches tool calls, not LLM outputs

---

## Immediate Action Items

### Today
- [ ] Post LinkedIn piece (self-observing loop story)
- [ ] Verify GitHub repo is public and README makes sense
- [ ] Commit uncommitted files on feat/semantic-search
- [ ] Store architecture docs in docs/architecture/

### This Week  
- [ ] Post second LinkedIn piece (418 sessions data analysis)
- [ ] Run Phase 2 A/B test for case study verification
- [ ] Send artifact trail Phase 2-3 prompt to Claude Code
- [ ] Fix Loopwright --print bug

### This Month
- [ ] Build CLAUDE.md generator from Engram data (Phase 0 of proxy)
- [ ] Build engram export --ml-features for training data
- [ ] Build MCP consulting demo for revenue
- [ ] Land first consulting client

### Next Month
- [ ] Smart MCP tools (engram_before_edit, engram_before_bash)
- [ ] Knowledge graph in SQLite (nodes + edges from existing data)
- [ ] Strategy scoring from artifact trail
- [ ] Connect Loopwright → Engram feedback loop

---

## The Vision in One Paragraph

Engram is the nervous system for AI agents. It observes every action an agent takes, builds a knowledge graph of codebase relationships and patterns, and fires intelligent reflexes — preventing forgotten files, warning about danger zones, and suggesting proven strategies. It works across any agent (Claude Code, Cursor, Codex) and any model (Anthropic, open source, local). Over time, the nervous system gets smarter with every session without the agent or codebase changing. Built as open infrastructure by Prosperity Labs — the protocol is free, expertise is what we sell.
