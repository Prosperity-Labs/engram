#!/usr/bin/env python3
"""Idempotent migration: add Loopwright tables to an existing sessions.db.

Safe to run multiple times — all CREATE statements use IF NOT EXISTS.

Usage:
    python scripts/migrate_loopwright.py                      # default ~/.config/engram/sessions.db
    python scripts/migrate_loopwright.py /path/to/sessions.db  # explicit path
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

LOOPWRIGHT_MIGRATION = """
-- Loopwright tables for worktree tracking, checkpoints, correction cycles
-- Added by migrate_loopwright.py — idempotent, safe to re-run.

CREATE TABLE IF NOT EXISTS worktrees (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT REFERENCES sessions(session_id),
    branch_name     TEXT NOT NULL,
    base_branch     TEXT NOT NULL DEFAULT 'main',
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','passed','failed','escalated','merged')),
    task_description TEXT,
    created_at      TEXT NOT NULL,
    resolved_at     TEXT
);

CREATE TABLE IF NOT EXISTS checkpoints (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    worktree_id         INTEGER NOT NULL REFERENCES worktrees(id),
    session_id          TEXT REFERENCES sessions(session_id),
    git_sha             TEXT,
    test_results        TEXT,
    artifact_snapshot   TEXT,
    graph_delta         TEXT,
    created_at          TEXT NOT NULL,
    label               TEXT
);

CREATE TABLE IF NOT EXISTS correction_cycles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    worktree_id         INTEGER NOT NULL REFERENCES worktrees(id),
    cycle_number        INTEGER NOT NULL,
    trigger_error       TEXT,
    error_context       TEXT,
    checkpoint_id       INTEGER REFERENCES checkpoints(id),
    agent_session_id    TEXT,
    outcome             TEXT CHECK(outcome IN ('passed','failed','escalated')),
    duration_seconds    INTEGER,
    created_at          TEXT NOT NULL
);

-- FTS5 for worktree task descriptions
CREATE VIRTUAL TABLE IF NOT EXISTS worktrees_fts USING fts5(
    task_description,
    branch_name,
    content='worktrees',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS worktrees_ai AFTER INSERT ON worktrees BEGIN
    INSERT INTO worktrees_fts(rowid, task_description, branch_name)
    VALUES (new.id, new.task_description, new.branch_name);
END;

CREATE TRIGGER IF NOT EXISTS worktrees_ad AFTER DELETE ON worktrees BEGIN
    INSERT INTO worktrees_fts(worktrees_fts, rowid, task_description, branch_name)
    VALUES ('delete', old.id, old.task_description, old.branch_name);
END;

CREATE TRIGGER IF NOT EXISTS worktrees_au AFTER UPDATE ON worktrees BEGIN
    INSERT INTO worktrees_fts(worktrees_fts, rowid, task_description, branch_name)
    VALUES ('delete', old.id, old.task_description, old.branch_name);
    INSERT INTO worktrees_fts(rowid, task_description, branch_name)
    VALUES (new.id, new.task_description, new.branch_name);
END;

-- FTS5 for correction cycle errors
CREATE VIRTUAL TABLE IF NOT EXISTS correction_cycles_fts USING fts5(
    trigger_error,
    content='correction_cycles',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS correction_cycles_ai AFTER INSERT ON correction_cycles BEGIN
    INSERT INTO correction_cycles_fts(rowid, trigger_error)
    VALUES (new.id, new.trigger_error);
END;

CREATE TRIGGER IF NOT EXISTS correction_cycles_ad AFTER DELETE ON correction_cycles BEGIN
    INSERT INTO correction_cycles_fts(correction_cycles_fts, rowid, trigger_error)
    VALUES ('delete', old.id, old.trigger_error);
END;

CREATE TRIGGER IF NOT EXISTS correction_cycles_au AFTER UPDATE ON correction_cycles BEGIN
    INSERT INTO correction_cycles_fts(correction_cycles_fts, rowid, trigger_error)
    VALUES ('delete', old.id, old.trigger_error);
    INSERT INTO correction_cycles_fts(rowid, trigger_error)
    VALUES (new.id, new.trigger_error);
END;

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_worktrees_session ON worktrees(session_id);
CREATE INDEX IF NOT EXISTS idx_worktrees_status ON worktrees(status);
CREATE INDEX IF NOT EXISTS idx_checkpoints_worktree ON checkpoints(worktree_id);
CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON checkpoints(session_id);
CREATE INDEX IF NOT EXISTS idx_correction_cycles_worktree ON correction_cycles(worktree_id);
CREATE INDEX IF NOT EXISTS idx_correction_cycles_checkpoint ON correction_cycles(checkpoint_id);
"""


def migrate(db_path: Path) -> None:
    if not db_path.exists():
        print(f"Database not found at {db_path} — creating fresh.")

    conn = sqlite3.connect(str(db_path), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        conn.executescript(LOOPWRIGHT_MIGRATION)
        conn.commit()
        print(f"Migration complete: {db_path}")

        for table in ("worktrees", "checkpoints", "correction_cycles"):
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table}: {count} rows")
    finally:
        conn.close()


def main() -> None:
    if len(sys.argv) > 1:
        db_path = Path(sys.argv[1])
    else:
        db_path = Path.home() / ".config" / "engram" / "sessions.db"

    migrate(db_path)


if __name__ == "__main__":
    main()
