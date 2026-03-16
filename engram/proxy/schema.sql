CREATE TABLE IF NOT EXISTS proxy_calls (
    id TEXT PRIMARY KEY,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    model TEXT,
    system_prompt_tokens INTEGER,
    message_count INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_creation_tokens INTEGER,
    cost_estimate_usd REAL,
    tools_used TEXT,       -- JSON array of tool names
    stop_reason TEXT,
    session_id TEXT,       -- link to session if detectable
    project TEXT,          -- detect from system prompt or cwd
    request_bytes INTEGER,
    response_bytes INTEGER,
    enrichment_variant TEXT       -- NULL=baseline, 'v1_slim'=enriched
);

CREATE INDEX IF NOT EXISTS idx_proxy_calls_timestamp ON proxy_calls(timestamp);
CREATE INDEX IF NOT EXISTS idx_proxy_calls_project ON proxy_calls(project);
CREATE INDEX IF NOT EXISTS idx_proxy_calls_model ON proxy_calls(model);

CREATE TABLE IF NOT EXISTS session_metrics (
    session_id TEXT PRIMARY KEY,
    project TEXT,
    enrichment_variant TEXT,
    turns_to_first_edit INTEGER,   -- calls until first Write/Edit tool_use
    exploration_turns INTEGER,     -- calls before first edit
    exploration_cost_usd REAL,
    total_turns INTEGER,
    total_cost_usd REAL,
    files_read_before_edit INTEGER,
    errors_count INTEGER,
    outcome TEXT,                   -- 'completed' | 'abandoned' | 'unknown'
    started_at DATETIME,
    ended_at DATETIME,
    agent_type TEXT,                -- 'claude' | 'cursor' | 'codex' (from Loopwright)
    correction_cycles INTEGER,     -- number of Loopwright correction cycles
    loop_outcome TEXT,             -- 'passed' | 'failed' | 'escalated' (from Loopwright)
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_session_metrics_project ON session_metrics(project);
CREATE INDEX IF NOT EXISTS idx_session_metrics_variant ON session_metrics(enrichment_variant);
