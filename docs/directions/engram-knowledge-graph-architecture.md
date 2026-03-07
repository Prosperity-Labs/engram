# Engram Knowledge Graph — Context Compression Architecture

## The Thesis

Bigger context windows don't help. They actively hurt.

GPT-5.4 needle-in-a-haystack accuracy:
- 97% at 16-32K tokens
- 86% at 64-128K tokens  
- 57% at 256-512K tokens
- 36% at 512K-1M tokens

The solution to long context isn't more context — it's the right context, 
structured as relationships, not flat text.

A knowledge graph is a compression algorithm for experience. 418 sessions, 
65,981 messages, 20,700 tool calls — compressed into a web of relationships 
that can be traversed in milliseconds and injected as 200-500 tokens instead 
of 200K tokens.

---

## What a Knowledge Graph Gives You That Flat Context Doesn't

```
FLAT CONTEXT (current approach):
  "Here are 50 relevant past sessions..."
  → Dumps into context window
  → Model accuracy degrades as context grows
  → At 200K tokens, it's missing 40% of what you put in

KNOWLEDGE GRAPH:
  Task: "Fix webhook handler"
  
  Graph traversal:
    webhook_handler → DEPENDS_ON → alchemy_client
    webhook_handler → CO_CHANGES_WITH → validators, endpoints, schemas
    webhook_handler → FAILED_BECAUSE → IAM_permissions (3 sessions)
    webhook_handler → TESTED_BY → webhook.test.ts
    IAM_permissions → SOLVED_BY → "use testnet API key"
    
  Inject only the subgraph: 5 relationships, ~200 tokens
  Not 50 sessions at 200K tokens
```

---

## Three Functions of the Graph

### Navigate
Given where the agent is right now (which file, which task), the graph 
tells it what's nearby. Not "here are 50 relevant sessions" but "this 
file connects to these 4 files, this error pattern, and this proven 
strategy." The agent sees the map, not the entire territory.

### Remember
The graph encodes what happened without storing the full history. 
"This approach failed 3 times, this approach worked" is a relationship, 
not a 50,000 token session transcript. Experience becomes structure.

### Predict
Flows that succeeded repeatedly become paths in the graph. When a 
similar task arrives, the graph already knows the sequence of files, 
the likely errors, and the working strategy. The agent follows a 
proven path instead of exploring from scratch.

---

## Three-Tier Context Management

```
Layer 1: HOT — In the prompt (< 4K tokens)
  Active task, current file, immediate co-changes
  Graph query: "what's directly connected to what I'm touching?"
  Always injected. Zero latency.

Layer 2: WARM — Available via MCP tool call (< 32K tokens)  
  Related sessions, known failures, strategy suggestions
  Graph query: "what's within 2 hops of my current work?"
  Injected on demand when agent calls engram tools.

Layer 3: COLD — In the database, never in context
  Full session history, all artifact trails, all raw data
  Only accessed when explicitly searched.
  Never pollutes the context window.
```

This maps to the Codified Context paper's architecture:
- Hot = 660 lines, always loaded
- Warm = 9,300 lines via domain-expert agents  
- Cold = 16,250 lines via MCP retrieval server

But instead of manually curating tiers, the knowledge graph 
automatically determines what's hot, warm, and cold based on 
relevance to the current task.

---

## Node and Edge Types

### Nodes
```
File        — handlers.ts, validators.ts, etc.
Session     — each past session with outcome + cost
Error       — each distinct error pattern
Strategy    — each approach (read_tests_first, grep_for_error)
Decision    — each architectural choice
Concept     — webhook, auth, payments, KYC
Tool        — Claude Code, Cursor, Codex
Person      — developer (for team layer)
Flow        — reusable sequence of steps that succeeded
```

### Edges
```
File    → CO_CHANGES_WITH  → File      (weight = co-occurrence count)
File    → CAUSES_ERROR     → Error     (weight = error:write ratio)
File    → TESTED_BY        → File      (inferred from test co-access)
Session → TOUCHED          → File      (from artifact trail)
Session → USED_STRATEGY    → Strategy  (from evolutionary layer)
Error   → SOLVED_BY        → Strategy  (from session outcomes)
Concept → INVOLVES         → File      (inferred from session topics)
File    → READ_BY          → Tool      (cross-agent tracking)
Flow    → CONTAINS_STEP    → File      (ordered sequence)
Flow    → SUCCEEDS_FOR     → Concept   (which task types this flow works for)
```

### Edge Properties
```
weight:          strength of relationship (co-occurrence count)
evidence_count:  number of sessions supporting this edge
last_seen:       recency (for decay)
fitness:         success rate when this relationship was relevant
```

---

## Flow Reusability

When a problem has been solved before, the graph encodes not just 
the answer but the entire flow:

```
REUSABLE FLOW: "Fix webhook validation"

  Step 1: Read webhook-handler.ts
  Step 2: Read validators.ts (co-change)
  Step 3: Read webhook.test.ts (test file)
  Step 4: Edit validators.ts (add validation)
  Step 5: Edit webhook-handler.ts (pass field through)
  Step 6: Run tests
  Step 7: Deploy

  This flow succeeded 3 times with avg cost $2.10
  This flow failed when: skipping step 2 (validators)
```

Next time a similar task comes in, the graph doesn't dump 50 sessions 
into context. It says: "here's the flow that worked 3 times, here are 
the files in order, here's what to not skip." ~500 tokens. Surgically precise.

---

## Implementation Path

### Phase 1: Graph in SQLite (start here)
No new infrastructure. Two tables:

```sql
CREATE TABLE graph_nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,       -- file, session, error, strategy, concept, flow
    name TEXT NOT NULL,
    properties TEXT,          -- JSON
    created_at DATETIME,
    updated_at DATETIME
);

CREATE TABLE graph_edges (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relationship TEXT NOT NULL,  -- CO_CHANGES_WITH, CAUSES_ERROR, etc.
    weight REAL DEFAULT 1.0,
    evidence_count INTEGER DEFAULT 1,
    last_seen DATETIME,
    fitness REAL,
    properties TEXT,            -- JSON
    PRIMARY KEY (source_id, target_id, relationship),
    FOREIGN KEY (source_id) REFERENCES graph_nodes(id),
    FOREIGN KEY (target_id) REFERENCES graph_nodes(id)
);

-- Traversal via recursive CTEs
-- "What's connected to validators.ts within 2 hops?"
WITH RECURSIVE connected AS (
    SELECT target_id, relationship, weight, 1 as depth
    FROM graph_edges WHERE source_id = 'file:validators.ts'
    UNION ALL
    SELECT e.target_id, e.relationship, e.weight, c.depth + 1
    FROM graph_edges e JOIN connected c ON e.source_id = c.target_id
    WHERE c.depth < 2
)
SELECT * FROM connected ORDER BY weight DESC;
```

Populate from existing data:
- Co-change patterns → CO_CHANGES_WITH edges
- Danger zones → CAUSES_ERROR edges
- File hotspots → node properties
- Session-file relationships → TOUCHED edges

### Phase 2: Memgraph (when graph algorithms needed)
Migrate when you need:
- PageRank over files (importance scoring)
- Community detection (file clusters)
- Shortest path (how are two concepts connected?)
- Real-time graph updates during sessions

### Phase 3: Distributed graph (team layer)
Multiple teams' graphs federated.
Anonymized edges shared across teams.
"TypeScript API projects typically have this co-change structure."

---

## Why This Beats Every Current Approach

| Tool | Context Method | Limitation |
|------|---------------|------------|
| GRIP | 1,800 knowledge pieces, flat list with fitness decay | No relationships between pieces |
| Tastematter | Co-access queries, file heat metrics | Statistics, not a graph. No traversal. |
| Anthropic Auto Memory | Topic-organized markdown files | Manual organization, no cross-referencing |
| Open Brain | Vector embeddings in Postgres | Similarity search, not relationship traversal |
| Codified Context | Three-tier manually curated | Manual curation doesn't scale |
| **Engram** | **Knowledge graph with typed relationships** | **Auto-built from session data, traversable, compresses to minimal context** |

---

## Connection to Nervous System

The knowledge graph IS the integration layer of the nervous system:

```
Sensory layer (observation) → captures raw events
                ↓
Knowledge graph (integration) → events become relationships
                ↓  
Reflex layer (intervention) → graph queries → precise context injection
                ↓
Agent receives 200 tokens of structured wisdom
instead of 200K tokens of raw history
```

The graph is where raw observation becomes structured understanding.
It's the nervous system's memory — not stored as recordings, 
but as connections.
