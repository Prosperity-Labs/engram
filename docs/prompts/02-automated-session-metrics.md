## Add automated session metrics

Create engram/proxy/metrics.py

After each session ends (detect by 10+ min gap between proxy calls
on same project, or new session_id), auto-compute and store:

```sql
CREATE TABLE session_metrics (
    session_id TEXT PRIMARY KEY,
    project TEXT,
    enrichment_variant TEXT,
    turns_to_first_edit INTEGER,
    exploration_turns INTEGER,
    exploration_cost_usd REAL,
    total_turns INTEGER,
    total_cost_usd REAL,
    files_read_before_edit INTEGER,
    errors_count INTEGER,
    outcome TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

turns_to_first_edit = count of proxy_calls until first response
containing a Write or Edit tool_use block.

Add CLI: engram proxy metrics
Shows table of recent sessions with all fields, grouped by variant.

Test with existing proxy_calls data.

### Context
- proxy_calls table already has: tools_used, cost_estimate_usd, project, enrichment_variant, timestamp
- Session detection: group by project + 10min gap between consecutive calls
- Current data: 3,631 proxy calls, 2,956 baseline + 675 v1_slim
- The key metric is "turns-to-first-edit" — measures exploration waste
