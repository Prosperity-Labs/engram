"""Build system prompt enrichment from Engram session history.

Wraps generate_slim_brief() output in XML tags for clean injection
into Anthropic API system prompts.
"""

from __future__ import annotations

from engram.brief import generate_slim_brief
from engram.recall.session_db import SessionDB

# Minimum brief length to be worth injecting (skip near-empty briefs)
_MIN_BRIEF_LEN = 80


def _resolve_project(short_name: str, db: SessionDB) -> str | None:
    """Resolve a short project name (e.g. 'engram') to the full DB project path.

    The proxy extracts just the last directory component, but the sessions DB
    stores full paths like '-home-user-Desktop-development-engram'.
    Try exact match first, then suffix match.
    """
    with db._connect() as conn:
        # Exact match
        row = conn.execute(
            "SELECT project FROM sessions WHERE project = ? LIMIT 1",
            (short_name,),
        ).fetchone()
        if row:
            return row["project"]

        # Suffix match: project ends with the short name
        row = conn.execute(
            "SELECT project, COUNT(*) as cnt FROM sessions "
            "WHERE project LIKE ? GROUP BY project ORDER BY cnt DESC LIMIT 1",
            (f"%{short_name}",),
        ).fetchone()
        if row:
            return row["project"]

    return None


def build_enrichment(project: str, db: SessionDB) -> str | None:
    """Generate an enrichment block for the given project.

    Returns an XML-wrapped brief string, or None if the project has
    insufficient data to produce a meaningful enrichment.
    """
    # Resolve short proxy project name to full DB project path
    resolved = _resolve_project(project, db)
    if not resolved:
        return None

    brief = generate_slim_brief(db, resolved)
    if not brief or len(brief) < _MIN_BRIEF_LEN:
        return None

    return f"<engram-context>\n{brief}\n</engram-context>"
