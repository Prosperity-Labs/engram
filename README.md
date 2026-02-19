# Engram

Knowledge base for Claude Code sessions. Index, search, and monitor your AI agent sessions in real-time.

## Install

```
pip install -e .
```

## Usage

```bash
# One-shot stats
engram monitor

# Live monitoring (indexes active sessions every 10s)
engram monitor --watch

# Full-text search across all sessions
engram search webhook error
engram search "race condition" --role assistant
engram search deploy --limit 5
```

## How It Works

Engram tails your Claude Code JSONL session files (`~/.claude/projects/`), incrementally indexes new messages into a local SQLite database (`~/.config/engram/sessions.db`), and provides full-text search via FTS5.

- **LiveIndexer** — polls active sessions every N seconds, reads only new bytes via offset tracking
- **SessionDB** — SQLite with WAL mode, FTS5 virtual table with porter stemming
- **Monitor** — terminal dashboard with sparklines, role breakdown, tool usage bars
