# Replay Engine — Research & Market Validation

> **Date:** 2026-02-22 | **Sources:** AgentRR (arxiv), Sakura Sky, Vellum/Rely Health, Microsoft Research

---

## Academic Proof

**AgentRR — "Get Experience from Practice: LLM Agents with Record & Replay"**
arxiv.org/abs/2505.17716 — May 2025

Core proposal: record agent interaction traces, summarize into structured
"experiences", replay in subsequent similar tasks to guide behavior.
Multi-level experience abstraction: low-level for precise replay, high-level
for generalization across similar tasks.

This is the academic validation of exactly what Engram's replay engine would do.
Engram already has the record layer (JSONL). The replay and experience
abstraction is what's left to build.

---

## Why Replay Is Hard Without Engram's Foundation

From Sakura Sky's "Trustworthy AI Agents: Deterministic Replay":

"Debugging agent systems is fundamentally harder than debugging traditional
software. Logs, metrics, and traces show you what happened, but they cannot
reconstruct why it happened or the exact sequence of decisions that led to an
unexpected outcome. Once an LLM produces a faulty or surprising plan in
production, reproducing the exact path to that decision is functionally
impossible without specialized tooling."

**Engram's advantage:** Claude Code already writes the full execution trace
to JSONL. No SDK required. The foundation for deterministic replay is already
being captured.

---

## Replay as Governance, Not Just Debugging

"Deterministic replay is not just a debugging primitive. It is a foundational
capability for AI governance, operational assurance, and post-incident forensics."

Implication: replay engine isn't a developer tool — it's an enterprise
compliance tool. That's a different and larger buyer.

---

## Competitor Signal

**Vellum / Rely Health (production, healthcare):**
Rely Health uses Vellum's replay to debug patient-facing agents — reported
100x reduction in issue resolution time.

This confirms: people pay for replay in production. Healthcare is already
there. Developer tooling (Engram's wedge) is the next wave.

**Key difference from Vellum:**
Vellum requires SDK instrumentation. Engram requires nothing — Claude Code
already writes the traces. Zero friction to start.

---

## Microsoft Research Validation

debug-gym (August 2025) — Microsoft Research:
"The significant performance improvement validates that interactive debugging
with access to debugging traces is a promising research direction."

Agents with access to debugging traces significantly outperform agents without
them on SWE-bench benchmarks.

---

## Roadmap Position

Phase 2 — after core Engram (session memory, brief, artifact manifest) is solid.

The replay engine requires:
1. Artifact manifest (being built now)
2. Session JSONL parsing (done)
3. Execution tree reconstruction from artifact sequence
4. Fork point UI — select any node, branch from there
5. Context injection at fork point
6. Parallel run comparison (same task, different model/context)

---

*Research compiled February 2026*
