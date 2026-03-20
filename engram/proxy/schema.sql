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
    enrichment_variant TEXT,      -- NULL=baseline, 'v1_slim'=enriched
    agent_type TEXT,              -- NULL=interactive, 'claude'/'cursor'/'codex' from Loopwright
    turn_number INTEGER,          -- sequential turn within session (1-indexed)
    cumulative_input_tokens INTEGER  -- running total of input tokens in session up to this call
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
    session_length_category TEXT,  -- 'short' (<10 turns) | 'medium' (10-30) | 'long' (30+)
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_session_metrics_project ON session_metrics(project);
CREATE INDEX IF NOT EXISTS idx_session_metrics_variant ON session_metrics(enrichment_variant);

CREATE TABLE IF NOT EXISTS experiments (
    experiment_id TEXT PRIMARY KEY,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    task_prompt TEXT NOT NULL,
    task_complexity TEXT CHECK(task_complexity IN ('simple', 'medium', 'complex')),
    repo TEXT,
    agent_type TEXT,
    model TEXT,
    enriched_status TEXT,         -- 'passed' | 'failed' | 'error'
    baseline_status TEXT,         -- 'passed' | 'failed' | 'error'
    enriched_cycles INTEGER,
    baseline_cycles INTEGER,
    enriched_duration_ms INTEGER,
    baseline_duration_ms INTEGER,
    duration_delta_pct REAL,      -- (baseline - enriched) / baseline * 100
    enriched_cost_usd REAL,
    baseline_cost_usd REAL,
    enriched_session_id TEXT,     -- proxy session linkage
    baseline_session_id TEXT,     -- proxy session linkage
    enriched_turn_count INTEGER,
    baseline_turn_count INTEGER,
    outcome TEXT CHECK(outcome IN ('enriched_wins', 'baseline_wins', 'tie', 'inconclusive')),
    notes TEXT,
    tags TEXT                     -- JSON array of tags
);

CREATE INDEX IF NOT EXISTS idx_experiments_created ON experiments(created_at);
CREATE INDEX IF NOT EXISTS idx_experiments_complexity ON experiments(task_complexity);
CREATE INDEX IF NOT EXISTS idx_experiments_outcome ON experiments(outcome);

CREATE TABLE IF NOT EXISTS session_turn_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cumulative_cost_usd REAL,
    cache_hit_ratio REAL,        -- cache_read / (cache_read + input) for this turn
    tools_used TEXT,             -- JSON array of tool names
    UNIQUE(session_id, turn_number)
);

CREATE INDEX IF NOT EXISTS idx_session_turn_metrics_session
    ON session_turn_metrics(session_id);
