from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from engram.brief import generate_brief
from engram.recall.session_db import SessionDB


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fts_query_from_task(task_description: str) -> str:
    tokens = []
    for raw in task_description.replace("/", " ").replace("-", " ").split():
        token = "".join(ch for ch in raw if ch.isalnum() or ch == "_")
        if len(token) >= 3:
            tokens.append(token)
        if len(tokens) >= 6:
            break
    return " ".join(tokens) or "task"


def _recent_history_summary(db: SessionDB, task_description: str, limit: int = 5) -> dict[str, Any]:
    query = _fts_query_from_task(task_description)
    similar_worktrees = []
    similar_errors = []

    try:
        similar_worktrees = db.search_worktrees(query, limit=limit)
    except Exception:
        similar_worktrees = []

    try:
        similar_errors = db.search_correction_errors(query, limit=limit)
    except Exception:
        similar_errors = []

    session_hits: list[dict[str, Any]] = []
    try:
        for item in db.search(query, limit=limit, role="assistant"):
            session_hits.append(
                {
                    "session_id": item.get("session_id"),
                    "project": item.get("project"),
                    "timestamp": item.get("timestamp"),
                    "snippet": (item.get("snippet") or item.get("content") or "")[:200],
                }
            )
    except Exception:
        session_hits = []

    return {
        "query": query,
        "similar_worktrees": [
            {
                "id": row.get("id"),
                "branch_name": row.get("branch_name"),
                "status": row.get("status"),
                "task_description": row.get("task_description"),
                "ab_variant_label": row.get("ab_variant_label"),
            }
            for row in similar_worktrees
        ],
        "similar_errors": [
            {
                "worktree_id": row.get("worktree_id"),
                "trigger_error": row.get("trigger_error"),
                "outcome": row.get("outcome"),
            }
            for row in similar_errors
        ],
        "session_hits": session_hits,
    }


def _render_history_brief(
    task_description: str,
    history: dict[str, Any],
    project_brief_md: str | None = None,
) -> str:
    lines = [
        "# Engram A/B Task Brief (Variant A: history-aware)",
        "",
        "## Task",
        task_description.strip(),
        "",
        "## Prior Context (Engram)",
        f"- Query used: `{history['query']}`",
    ]

    worktrees = history.get("similar_worktrees") or []
    if worktrees:
        lines.append("- Similar worktrees:")
        for row in worktrees[:5]:
            lines.append(
                f"  - #{row.get('id')} `{row.get('branch_name')}` [{row.get('status')}]"
                f": {row.get('task_description')}"
            )
    else:
        lines.append("- Similar worktrees: none found")

    errors = history.get("similar_errors") or []
    if errors:
        lines.append("- Prior correction errors:")
        for row in errors[:5]:
            lines.append(
                f"  - worktree #{row.get('worktree_id')}: {row.get('trigger_error')} "
                f"(outcome={row.get('outcome')})"
            )
    else:
        lines.append("- Prior correction errors: none found")

    hits = history.get("session_hits") or []
    if hits:
        lines.append("- Relevant assistant session snippets:")
        for row in hits[:5]:
            lines.append(
                f"  - [{row.get('project') or 'unknown'}] {row.get('snippet')}"
            )
    else:
        lines.append("- Relevant assistant session snippets: none found")

    lines.extend(
        [
            "",
            "## Instructions",
            "- Use the prior context to avoid repeating failed approaches.",
            "- Call out when prior history appears irrelevant to the current task.",
        ]
    )

    if project_brief_md:
        lines.extend(["", "## Project Brief", project_brief_md.strip()])

    return "\n".join(lines).strip() + "\n"


def _render_cold_brief(task_description: str) -> str:
    return (
        "# Engram A/B Task Brief (Variant B: cold-start)\n\n"
        "## Task\n"
        f"{task_description.strip()}\n\n"
        "## Instructions\n"
        "- No Engram history is injected for this run.\n"
        "- Solve from first principles and local repository context only.\n"
    )


def generate_ab_briefs(
    task_description: str,
    session_db_path: str | os.PathLike[str],
    variant_a_config: dict[str, Any] | None = None,
    variant_b_config: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Generate two brief variants for A/B comparison from one task.

    Variant A includes Engram history; Variant B is a cold-start baseline.
    """
    db = SessionDB(db_path=session_db_path)
    variant_a_config = variant_a_config or {}
    variant_b_config = variant_b_config or {}

    history = _recent_history_summary(
        db,
        task_description,
        limit=int(variant_a_config.get("history_limit", 5)),
    )

    project_brief_md = None
    project = variant_a_config.get("project")
    if project:
        try:
            project_brief_md = generate_brief(db, str(project), format="markdown")
        except Exception:
            project_brief_md = None

    a_content = _render_history_brief(task_description, history, project_brief_md)
    b_content = _render_cold_brief(task_description)

    return {
        "variant_a": {
            "variant_label": str(variant_a_config.get("label", "A")),
            "content": a_content,
            "metadata": {
                "mode": "history_aware",
                "generated_at": _now_iso(),
                "task_description": task_description,
                "history_query": history["query"],
                "similar_worktrees_count": len(history["similar_worktrees"]),
                "similar_errors_count": len(history["similar_errors"]),
                "session_hits_count": len(history["session_hits"]),
                "config": variant_a_config,
            },
        },
        "variant_b": {
            "variant_label": str(variant_b_config.get("label", "B")),
            "content": b_content,
            "metadata": {
                "mode": "cold_start",
                "generated_at": _now_iso(),
                "task_description": task_description,
                "config": variant_b_config,
            },
        },
    }


def write_brief_to_worktree(
    worktree_path: str | os.PathLike[str],
    brief_content: str,
    variant_label: str,
) -> dict[str, Any]:
    """Append an A/B brief to `CLAUDE.md` and record the variant on the worktree row.

    Uses `LOOPWRIGHT_WORKTREE_ID` and optional `LOOPWRIGHT_SESSION_DB_PATH` env vars
    to persist the variant metadata into `sessions.db`.
    """
    wt_path = Path(worktree_path)
    claude_md = wt_path / "CLAUDE.md"
    claude_md.parent.mkdir(parents=True, exist_ok=True)
    existed_before = claude_md.exists()

    marker = f"\n\n<!-- ENGRAM_AB_BRIEF:{variant_label} -->\n"
    payload = f"{marker}{brief_content.rstrip()}\n"
    if existed_before:
        claude_md.write_text(claude_md.read_text(encoding="utf-8") + payload, encoding="utf-8")
    else:
        claude_md.write_text(payload.lstrip("\n"), encoding="utf-8")

    worktree_id = os.environ.get("LOOPWRIGHT_WORKTREE_ID")
    if worktree_id:
        try:
            worktree_id_int = int(worktree_id)
        except ValueError as exc:
            raise ValueError(f"Invalid LOOPWRIGHT_WORKTREE_ID={worktree_id!r}") from exc

        db = SessionDB(db_path=os.environ.get("LOOPWRIGHT_SESSION_DB_PATH"))
        db.update_worktree_ab_metadata(
            worktree_id_int,
            variant_label=variant_label,
            brief_metadata={
                "variant_label": variant_label,
                "claude_md_path": str(claude_md),
                "written_at": _now_iso(),
                "bytes": len(brief_content.encode("utf-8")),
            },
        )

    return {
        "claude_md": str(claude_md),
        "variant_label": variant_label,
        "appended": existed_before,
    }
