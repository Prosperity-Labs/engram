"""Engram MCP server — exposes session history and analytics to AI agents.

Run with: engram mcp
Register in Claude Code: {"engram": {"command": "uvx", "args": ["engram", "mcp"]}}
"""

from __future__ import annotations

import json
import re

from mcp.server.fastmcp import FastMCP

server = FastMCP(
    "engram",
    instructions=(
        "AI coding session history and analytics. "
        "Search past sessions, get file history, danger zones, "
        "project briefs, and cost analytics across Claude Code, Codex, and Cursor.\n\n"
        "AUTO-RECALL: When the user says phrases like "
        '"we already figured this out", "we did this before", '
        '"we solved this", "how did we do X", "what was the command for Y", '
        '"remember when we", "didn\'t we already", "last time we" — '
        "IMMEDIATELY call engram_recall with the user's message BEFORE responding. "
        "Use the returned context to inform your answer. "
        "This prevents the user from having to manually search for past work."
    ),
)


def _get_db():
    """Lazy import to avoid import-time side effects."""
    from engram.recall.session_db import SessionDB
    return SessionDB()


def _sanitize_fts_query(raw: str) -> str:
    """Sanitize user input for FTS5 MATCH queries."""
    parts = []
    for segment in re.split(r'(".*?")', raw):
        if segment.startswith('"') and segment.endswith('"'):
            parts.append(segment)
        else:
            for tok in segment.split():
                escaped = tok.replace('"', '""')
                parts.append(f'"{escaped}"')
    return " ".join(parts)


# ── Tool 1: Search ──────────────────────────────────────────────────

@server.tool()
def engram_search(
    query: str,
    limit: int = 10,
    project: str | None = None,
) -> str:
    """Search across all AI coding sessions. Returns matching messages with context.

    Args:
        query: Search terms (supports AND, OR, NOT, "exact phrases")
        limit: Max results to return (default 10)
        project: Filter to a specific project name
    """
    from engram.query_rewriter import rewrite_query

    db = _get_db()
    rewritten = rewrite_query(query)
    from engram.recall import vector_search

    use_semantic = vector_search.is_available() and vector_search.has_embeddings(db.conn)
    search_fn = db.semantic_search if use_semantic else db.search

    # Search each keyword independently, collect all results
    all_results: dict[tuple, dict] = {}  # (session_id, sequence) → result
    keyword_hits: dict[tuple, int] = {}  # (session_id, sequence) → hit count

    for fts_q in rewritten["fts_queries"]:
        try:
            results = search_fn(fts_q, limit=limit * 3)  # oversample for merging
        except Exception:
            continue  # skip keywords that FTS5 rejects

        if project:
            results = [r for r in results if r.get("project") == project]

        for r in results:
            key = (r["session_id"], r.get("sequence", r.get("snippet", "")[:50]))
            if key not in all_results:
                all_results[key] = r
                keyword_hits[key] = 0
            keyword_hits[key] += 1

    if not all_results:
        return json.dumps({
            "results": [],
            "query_interpreted_as": rewritten["keywords"],
            "message": f"No results for: {query}",
        })

    # Rank: more keyword hits = more relevant, then by recency
    ranked = sorted(
        all_results.values(),
        key=lambda r: (
            keyword_hits[(r["session_id"], r.get("sequence", r.get("snippet", "")[:50]))],
            r.get("timestamp") or "",
        ),
        reverse=True,
    )

    output = []
    for r in ranked[:limit]:
        output.append({
            "session_id": r["session_id"],
            "project": r["project"],
            "role": r["role"],
            "tool_name": r["tool_name"],
            "snippet": r["snippet"],
            "timestamp": r["timestamp"],
        })

    return json.dumps({
        "results": output,
        "query_interpreted_as": rewritten["keywords"],
        "count": len(output),
    })


# ── Tool 2: Recall ─────────────────────────────────────────────────

@server.tool()
def engram_recall(
    user_message: str,
    project: str | None = None,
) -> str:
    """Auto-recall past work when user references something done before.

    Call this IMMEDIATELY when the user says things like:
    - "we already figured this out"
    - "we did this before"
    - "how did we do X"
    - "what was the command for Y"
    - "remember when we..."
    - "didn't we already..."
    - "last time we..."

    Args:
        user_message: The user's full message (intent detection extracts the topic)
        project: Filter to a specific project name
    """
    from engram.query_rewriter import detect_recall_intent, rewrite_query

    db = _get_db()

    # Try intent detection first — strips recall phrases to get the topic
    intent = detect_recall_intent(user_message)
    if intent:
        keywords = intent["keywords"]
    else:
        # Fallback: treat the whole message as a search query
        rewritten = rewrite_query(user_message)
        keywords = rewritten["keywords"]

    if not keywords:
        return json.dumps({
            "recall": [],
            "message": "Could not extract search terms from the message.",
        })

    from engram.recall import vector_search

    use_semantic = vector_search.is_available() and vector_search.has_embeddings(db.conn)
    search_fn = db.semantic_search if use_semantic else db.search

    # Search each keyword, merge results
    all_results: dict[tuple, dict] = {}
    keyword_hits: dict[tuple, int] = {}

    for kw in keywords:
        fts_q = f'"{kw}"'
        try:
            results = search_fn(fts_q, limit=15)
        except Exception:
            continue

        if project:
            results = [r for r in results if r.get("project") == project]

        for r in results:
            key = (r["session_id"], r.get("sequence", r.get("snippet", "")[:50]))
            if key not in all_results:
                all_results[key] = r
                keyword_hits[key] = 0
            keyword_hits[key] += 1

    if not all_results:
        return json.dumps({
            "recall": [],
            "keywords_searched": keywords,
            "message": f"No past sessions found for: {' '.join(keywords)}",
        })

    # Rank by keyword hit count, then recency
    ranked = sorted(
        all_results.values(),
        key=lambda r: (
            keyword_hits[(r["session_id"], r.get("sequence", r.get("snippet", "")[:50]))],
            r.get("timestamp") or "",
        ),
        reverse=True,
    )

    # Return top 3, formatted for context injection
    recall = []
    for r in ranked[:3]:
        recall.append({
            "project": r.get("project"),
            "role": r.get("role"),
            "tool_name": r.get("tool_name"),
            "snippet": r.get("snippet"),
            "timestamp": r.get("timestamp"),
            "session_id": r.get("session_id"),
        })

    return json.dumps({
        "recall": recall,
        "keywords_searched": keywords,
        "topic": intent["topic"] if intent else user_message,
        "count": len(recall),
    })


# ── Tool 3: File History ────────────────────────────────────────────

@server.tool()
def engram_file_history(file_path: str) -> str:
    """Get history for a specific file: reads, writes, errors across all sessions.

    Args:
        file_path: Absolute or relative path to the file
    """
    db = _get_db()
    from engram.hooks import file_context
    from engram.recall.artifact_extractor import ArtifactExtractor

    context = file_context(db, file_path)
    extractor = ArtifactExtractor(db)

    artifacts = extractor.get_artifacts(artifact_type=None, limit=50)
    file_artifacts = [a for a in artifacts if a["target"] == file_path]

    result = {
        "file_path": file_path,
        "summary": context or "No history found for this file.",
        "artifacts": file_artifacts[:20],
    }
    return json.dumps(result, default=str)


# ── Tool 4: Session List ────────────────────────────────────────────

@server.tool()
def engram_session_list(
    project: str | None = None,
    limit: int = 20,
) -> str:
    """List AI coding sessions with message counts, costs, and dates.

    Args:
        project: Filter to a specific project name
        limit: Max sessions to return (default 20)
    """
    db = _get_db()
    from engram.sessions import list_sessions

    sessions = list_sessions(db, project=project, limit=limit)
    return json.dumps({"sessions": sessions, "count": len(sessions)}, default=str)


# ── Tool 5: Project Brief ───────────────────────────────────────────

@server.tool()
def engram_project_brief(
    project: str,
    slim: bool = True,
) -> str:
    """Generate a project brief: key files, danger zones, co-change clusters.

    Args:
        project: Project name (use engram_session_list to find project names)
        slim: If true, generate compact brief (<500 tokens). If false, full brief.
    """
    db = _get_db()
    from engram.brief import generate_brief

    brief = generate_brief(db, project=project, format="markdown", slim=slim)
    return brief


# ── Tool 6: Danger Zones ────────────────────────────────────────────

@server.tool()
def engram_danger_zones(project: str) -> str:
    """Files with high error-to-write ratios — where agents struggle.

    Args:
        project: Project name
    """
    db = _get_db()
    from engram.brief import _dangerous_files

    dangerous = _dangerous_files(db, project)
    if not dangerous:
        return json.dumps({
            "project": project,
            "danger_zones": [],
            "message": "No danger zones found for this project.",
        })

    return json.dumps({"project": project, "danger_zones": dangerous})


# ── Tool 7: Artifacts ───────────────────────────────────────────────

@server.tool()
def engram_artifacts(
    session_id: str | None = None,
    project: str | None = None,
    artifact_type: str | None = None,
    limit: int = 50,
) -> str:
    """Query extracted artifacts (file_read, file_write, command, error, api_call).

    Args:
        session_id: Filter to a specific session
        project: Filter to a specific project
        artifact_type: Filter by type: file_read, file_write, file_create, command, api_call, error
        limit: Max results (default 50)
    """
    db = _get_db()
    from engram.recall.artifact_extractor import ArtifactExtractor

    extractor = ArtifactExtractor(db)
    artifacts = extractor.get_artifacts(
        session_id=session_id,
        project=project,
        artifact_type=artifact_type,
        limit=limit,
    )
    return json.dumps({"artifacts": artifacts, "count": len(artifacts)}, default=str)


# ── Tool 8: Session Stats ───────────────────────────────────────────

@server.tool()
def engram_session_stats(
    session_id: str | None = None,
    project: str | None = None,
) -> str:
    """Analytics: exploration ratio, mutation ratio, error rate, top tools, costs.

    Args:
        session_id: Get stats for a specific session
        project: Filter project stats to a specific project
    """
    db = _get_db()
    from engram.stats import compute_project_stats, compute_session_stats

    if session_id:
        stats = compute_session_stats(db, session_id)
        return json.dumps({"stats": stats}, default=str)

    all_stats = compute_project_stats(db)
    if project:
        all_stats = [s for s in all_stats if s.get("project") == project]

    return json.dumps({"stats": all_stats, "count": len(all_stats)}, default=str)


# ── Tool 9: Insights ────────────────────────────────────────────────

@server.tool()
def engram_insights() -> str:
    """Global analytics: cache efficiency, burn sessions, expensive sessions, topics."""
    db = _get_db()
    data = db.insights()
    kb_stats = db.stats()
    data["knowledge_base"] = kb_stats
    return json.dumps(data, default=str)


# ── Resource: Projects ──────────────────────────────────────────────

@server.resource("engram://projects")
def list_projects() -> str:
    """List all indexed projects with session counts."""
    db = _get_db()
    with db._connect() as conn:
        rows = conn.execute(
            """SELECT project, COUNT(*) as sessions, SUM(message_count) as messages
               FROM sessions
               WHERE project IS NOT NULL
               GROUP BY project
               ORDER BY sessions DESC"""
        ).fetchall()

    projects = [
        {
            "project": row["project"],
            "sessions": row["sessions"],
            "messages": row["messages"],
        }
        for row in rows
    ]
    return json.dumps({"projects": projects}, default=str)
