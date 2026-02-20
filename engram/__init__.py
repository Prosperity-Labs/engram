"""Engram — Cross-agent memory and artifact tracking.

Supports Claude Code, Cursor, and Codex.

Usage:
    from engram import SessionIndexer, search

    idx = SessionIndexer()
    idx.install()                          # Index all discoverable sessions
    results = search("webhook bug")        # Full-text search across sessions
    stats = idx.stats()                    # DB stats
"""

__version__ = "0.1.0"

from engram.recall.session_db import SessionDB as SessionIndexer


def search(query: str, limit: int = 20, role: str | None = None, session_id: str | None = None) -> list[dict]:
    """Search across all indexed sessions.

    Args:
        query: FTS5 query (supports AND, OR, NOT, "phrases", prefix*)
        limit: Max results
        role: Filter by role (user, assistant, summary)
        session_id: Filter to specific session

    Returns:
        List of dicts with: session_id, project, role, tool_name, snippet, content, timestamp, rank
    """
    db = SessionIndexer()
    return db.search(query, limit=limit, role=role, session_id=session_id)


__all__ = ["SessionIndexer", "search", "__version__"]
