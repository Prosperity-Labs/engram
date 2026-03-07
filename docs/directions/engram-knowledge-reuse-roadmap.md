# Engram Knowledge Reuse System — Roadmap Addition

## The Problem

We research things deeply, then lose them. Tonight alone we investigated:
- GRIP's architecture (genome, fitness, RSI loops, safety gates)
- Tastematter's context graph approach
- Codified Context's three-tier memory architecture
- Insightful.io's workforce monitoring model
- Claude-spend's viral distribution strategy
- Avi Pilcer's ghost token analysis
- Olivier Legit's CLAUDE.md multi-agent structure
- Anthropic's auto memory system

None of this is queryable. Next time we make a competitive decision 
or architectural choice, we'll re-research from scratch — or worse, 
make decisions without information we already gathered.

## The Vision

Every piece of research becomes a knowledge artifact in Engram.
When a session touches a related topic, the relevant research 
surfaces automatically via the proxy layer's reflex system.

```
Developer starts session: "Design the safety gate system"

ENGRAM REFLEX: KNOWLEDGE_REUSE (AUGMENT)
┌────────────────────────────────────────────────────┐
│ Related research found:                             │
│                                                     │
│ GRIP Safety Gates (researched 2026-03-05):          │
│   10 deterministic Python gates, return DENY        │
│   confidence-gate, context-gate, secrets-detection  │
│   destructive-git, production-safety                │
│   Key insight: "The AI cannot argue with a Python   │
│   function" — deterministic, not probabilistic      │
│   Freshness: 2 days old ✓                           │
│                                                     │
│ Anthropic Auto Memory (researched 2026-03-05):      │
│   Native CLAUDE.md + MEMORY.md system               │
│   200-line cap forces conciseness                   │
│   Topic-based file separation                       │
│   Freshness: 2 days old ✓                           │
│                                                     │
│ Codified Context (researched 2026-03-05):           │
│   Three-tier: hot memory (660 lines, always loaded) │
│   + 19 domain-expert agents (9,300 lines)           │
│   + cold memory via MCP retrieval (16,250 lines)    │
│   Freshness: 2 days old ✓                           │
└────────────────────────────────────────────────────┘
```

## Knowledge Artifact Types

### 1. Competitive Intelligence
What competitors are building, their architecture, their positioning.
Surfaces when: working on features that overlap with competitors.
Refresh cycle: every 2-4 weeks (market moves fast).

```yaml
type: competitive_intel
subject: GRIP
researched: 2026-03-05
refresh_by: 2026-03-19
tags: [safety_gates, RSI, genome, memory, multi_agent]
key_findings:
  - 131 skills, 21 agents, 27 modes, 10 safety gates
  - Recursive self-improvement via genome/fitness model
  - 1,800+ knowledge pieces with fitness-based decay
  - Pricing: $150 for 90-min AI Konsult
  - Single-agent (Claude Code focused)
  - Strengths: autonomous evolution, safety mechanisms
  - Weaknesses: no cross-agent, no team observability
differentiators_vs_engram:
  - GRIP is an operating system; Engram is a nervous system
  - GRIP makes agents better; Engram makes agents visible
  - GRIP is single-agent; Engram is cross-agent
source_urls:
  - https://grip-preview.vercel.app/
```

### 2. Technical Research
How things work under the hood. API findings, protocol details, 
data format discoveries.
Surfaces when: building features that touch these systems.
Refresh cycle: every 4-8 weeks (technical details change less often).

```yaml
type: technical_research
subject: Claude Code JSONL structure
researched: 2026-03-03
refresh_by: 2026-04-03
tags: [jsonl, tool_calls, artifact_trail, state_diff]
key_findings:
  - Edit tool calls contain old_string and new_string (full diffs)
  - Write tool calls contain full file content
  - Bash calls capture command, exit code, stdout/stderr
  - tool_use_id links request to response
  - Ghost tokens: ~25,000 per request (Avi Pilcer finding)
  - Each bash call adds ~800 tokens of hidden context
refresh_triggers:
  - Claude Code major version update
  - New tool types added
  - MCP spec changes
```

### 3. Market / Distribution Research
What works for getting users. Pricing models, launch strategies,
viral patterns.
Surfaces when: working on GTM, content, or pricing decisions.
Refresh cycle: every 2 weeks (distribution meta changes fast).

```yaml
type: market_research
subject: claude-spend viral launch
researched: 2026-03-05
refresh_by: 2026-03-19
tags: [distribution, viral, npm, cost_visibility, launch]
key_findings:
  - Single command: npx claude-spend
  - 200+ users from Reddit + LinkedIn
  - Built by a PM, not an engineer
  - Key: one problem, one command, one result
  - Data never leaves machine (trust signal)
  - Pain point: "You hit your limit. You don't know why."
  - No install, no signup, no config
lessons_for_engram:
  - Simplicity of entry point matters more than feature depth
  - Cost visibility alone is enough to get users
  - Reddit r/ClaudeAI is a viable launch channel
  - "Your data stays local" is a key trust message
```

### 4. Architectural Decisions
Why we chose X over Y. The reasoning, tradeoffs, and context
that led to a decision.
Surfaces when: revisiting or questioning past decisions.
Refresh cycle: never expires (but context may change).

```yaml
type: architecture_decision
subject: JSONL as source of truth vs SQLite for artifact trail
decided: 2026-03-03
tags: [artifact_trail, storage, architecture]
decision: Parse from raw JSONL on-demand, not SQLite
reasoning:
  - JSONL has full tool payloads (old_string/new_string)
  - SQLite stores messages but not tool payloads
  - Avoids migration complexity
  - On-demand parsing keeps it simple for v1
tradeoffs:
  - Slower for repeated queries on same session
  - Will need SQLite indexing later for ML features
  - JSONL files could be deleted/moved by Claude Code updates
revisit_when:
  - Query latency becomes noticeable
  - ML pipeline needs indexed artifact data
  - Multiple users querying same session data
```

### 5. User/Founder Conversations
Insights from calls and conversations with other builders.
Surfaces when: making product or positioning decisions.
Refresh cycle: after each follow-up conversation.

```yaml
type: conversation_intel
subject: GRIP founder call
date: 2026-03-05
tags: [GRIP, RSI, competitive, collaboration]
key_insights:
  - Recursive self-improvement is real, not just branding
  - Genome with fitness-based evolution across generations
  - "Delight metric" emerged spontaneously from RSI loop
  - Founder renamed ai_delight to system_health (philosophical discipline)
  - South Africa based (CodeTonight/ENTER Konsult)
  - Potential collaborator, not just competitor
open_questions:
  - Who is paying for GRIP?
  - Multi-agent plans?
  - Interest in Engram as observability layer for GRIP?
follow_up: Schedule second call after Engram dashboard is built
```

## How It Works Technically

### Storage
New table in Engram's SQLite:

```sql
CREATE TABLE knowledge_artifacts (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,          -- competitive_intel, technical_research, etc.
    subject TEXT NOT NULL,
    researched_at DATETIME,
    refresh_by DATETIME,
    tags TEXT,                   -- JSON array
    content TEXT,                -- Full YAML/markdown content
    summary TEXT,                -- One-line summary for quick display
    is_stale BOOLEAN DEFAULT 0, -- Set when refresh_by has passed
    source_session_id TEXT,      -- Which Engram session produced this
    FOREIGN KEY (source_session_id) REFERENCES sessions(session_id)
);

CREATE VIRTUAL TABLE knowledge_fts USING fts5(
    subject, tags, content, summary
);
```

### Capture
Two modes:

**Manual:** After a research session, run:
```bash
engram capture --type competitive_intel --subject "GRIP" --refresh 14d
# Opens editor with template, you fill in key findings
```

**Auto-extract:** Engram analyzes session content and suggests knowledge artifacts.
When a session contains heavy web search, document reading, or comparison work,
the brief generator flags it as potential research and offers to capture.

```
Session 06df494d ended. Engram detected research patterns:
  - 6 web searches about competitor tools
  - 12 document reads about MCP architecture
  - Multiple comparison/analysis patterns

Suggest capturing as knowledge artifact? [Y/n]
```

### Retrieval (Hooks Integration)
The proxy layer's reflex system queries knowledge artifacts:

```python
# In the rules engine:
Rule(
    name="knowledge_reuse",
    trigger=lambda tc: tc.sequence <= 3,  # first 3 tool calls only
    action=lambda tc, k: surface_relevant_knowledge(tc, k),
    priority=75,
    cooldown=3600,  # once per hour (session start only)
)

def surface_relevant_knowledge(tool_call, knowledge_engine):
    # Extract topic from session context
    topic = extract_session_topic(tool_call)
    
    # Search knowledge artifacts
    artifacts = knowledge_engine.search_knowledge(topic, limit=3)
    
    if not artifacts:
        return Intervention(type=OBSERVE)
    
    # Check freshness
    stale = [a for a in artifacts if a.is_stale]
    fresh = [a for a in artifacts if not a.is_stale]
    
    context = format_knowledge_block(fresh)
    
    if stale:
        context += f"\n⚠ {len(stale)} artifacts are stale and may need re-research"
    
    return Intervention(
        type=AUGMENT,
        content=context
    )
```

### Freshness & Re-research
Knowledge decays. The system tracks it:

```bash
# Show what needs re-researching
engram knowledge --stale

  STALE KNOWLEDGE (past refresh_by date):
  ────────────────────────────────────────
  ⚠ GRIP architecture (14 days old, refresh was 7 days ago)
  ⚠ claude-spend user count (10 days old, refresh was 7 days ago)
  ⚠ MCP spec updates (30 days old, refresh was 14 days ago)

# Trigger re-research for a specific artifact
engram refresh "GRIP"
# Opens session with previous findings pre-loaded
# Agent searches for updates, diffs against previous version
# Highlights what changed
```

The refresh cycle produces a diff:

```
GRIP Research Refresh — 2026-03-19
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  UNCHANGED:
    - Still 10 safety gates
    - Still invite-only
    - Still single-agent

  CHANGED:
    + Now 147 skills (was 131)
    + New "pair-mode" feature launched publicly
    + Pricing changed: $200 for konsult (was $150)
    
  NEW:
    + Published case study: "40% reduction in onboarding time"
    + Announced Cursor adapter in development (!)
    
  ⚠ ALERT: GRIP is building Cursor support. 
    This directly competes with Engram's cross-agent differentiator.
    Consider accelerating CursorAdapter work.
```

## Integration with Existing Systems

### With Brief Generator
`engram brief` already generates structured session summaries.
Add a section: "Related Knowledge" that pulls relevant artifacts.

### With Recall
`engram_recall` already searches past sessions.
Extend to also search knowledge_artifacts table.
"We researched this before" → surfaces the artifact, not raw session content.

### With Evolutionary Layer
Strategy selection informed by competitive knowledge.
"GRIP uses fitness-based decay for memory. Our strategies table 
should implement similar decay." — surfaced automatically when 
building the strategies feature.

### With Content Pipeline
When writing a post, surface relevant market research.
"claude-spend went viral with one-command install. 
Consider similar entry point for Engram."

## Capture Taxonomy

```
                    KNOWLEDGE TYPES
                    ═══════════════
  
  ┌──────────────────┐  ┌──────────────────┐
  │  COMPETITIVE      │  │  TECHNICAL        │
  │  INTELLIGENCE     │  │  RESEARCH         │
  │                   │  │                   │
  │  Who builds what  │  │  How things work  │
  │  Refresh: 2-4 wk  │  │  Refresh: 4-8 wk  │
  └──────────────────┘  └──────────────────┘
  
  ┌──────────────────┐  ┌──────────────────┐
  │  MARKET /         │  │  ARCHITECTURE     │
  │  DISTRIBUTION     │  │  DECISIONS        │
  │                   │  │                   │
  │  What works for   │  │  Why we chose X   │
  │  getting users    │  │  over Y           │
  │  Refresh: 2 wk    │  │  Refresh: never   │
  └──────────────────┘  └──────────────────┘
  
  ┌──────────────────┐  ┌──────────────────┐
  │  CONVERSATION     │  │  EXPERIMENT       │
  │  INSIGHTS         │  │  RESULTS          │
  │                   │  │                   │
  │  What people told │  │  What we tested   │
  │  us               │  │  and measured     │
  │  Refresh: per     │  │  Refresh: when    │
  │  follow-up        │  │  code changes     │
  └──────────────────┘  └──────────────────┘
```

## CLI Commands

```bash
# Capture new knowledge
engram capture --type competitive_intel --subject "GRIP" --refresh 14d

# List all knowledge
engram knowledge

# Search knowledge
engram knowledge search "safety gates"

# Show stale items needing refresh
engram knowledge --stale

# Refresh a specific artifact (re-research)
engram refresh "GRIP"

# Show knowledge relevant to current project
engram knowledge --project engram

# Export all knowledge as markdown
engram knowledge export > research-vault.md
```

## Success Metrics

- Knowledge artifacts captured per week: target 3-5
- Stale artifact refresh rate: < 7 days past due
- Knowledge surfaced per session (via proxy): 0.5-1 average
- Research time saved by reuse: measurable via session comparison
  (sessions where knowledge was surfaced vs cold research sessions)

## Priority

This system is most valuable AFTER the proxy layer exists (Phase 1+).
Without the proxy, knowledge artifacts are just a manual lookup — useful 
but not transformative. With the proxy, they surface automatically at 
the right moment, which is the real value.

Build order:
1. Knowledge table + capture CLI (standalone value, 1-2 days)
2. FTS search across knowledge (1 day)
3. Integration with engram_recall MCP tool (1 day)
4. Proxy reflex for auto-surfacing (after proxy Phase 1)
5. Auto-extract from sessions (after proxy Phase 2)
6. Freshness tracking + refresh workflow (1 day)
