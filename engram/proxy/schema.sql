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
    response_bytes INTEGER
);

CREATE INDEX IF NOT EXISTS idx_proxy_calls_timestamp ON proxy_calls(timestamp);
CREATE INDEX IF NOT EXISTS idx_proxy_calls_project ON proxy_calls(project);
CREATE INDEX IF NOT EXISTS idx_proxy_calls_model ON proxy_calls(model);
