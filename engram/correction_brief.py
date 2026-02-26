"""Correction brief generator for Loopwright correction agents.

Generates context-rich markdown briefs that tell a correction agent what
failed, what was already tried, and what similar errors looked like — so it
doesn't repeat the same mistakes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from engram.recall.session_db import SessionDB

MAX_CORRECTION_CYCLES = 3


def _extract_fts_tokens(text: str, max_tokens: int = 6) -> str:
    """Build a simple FTS query from free-form error text."""
    tokens = []
    for raw in text.replace("/", " ").replace("-", " ").replace(":", " ").split():
        token = "".join(ch for ch in raw if ch.isalnum() or ch == "_")
        if len(token) >= 3:
            tokens.append(token)
        if len(tokens) >= max_tokens:
            break
    return " ".join(tokens) or "error"


def _render_error_context(error_context: dict | None) -> str:
    if not error_context:
        return ""

    lines: list[str] = []
    errors = error_context.get("errors") or []
    if errors:
        lines.append("\n### Structured Error Context")
        for err in errors[:5]:
            loc = err.get("file", "?")
            if err.get("line"):
                loc += f":{err['line']}"
            lines.append(f"- **File:** `{loc}`")
            if err.get("type"):
                lines.append(f"  - Type: {err['type']}")
            if err.get("message"):
                lines.append(f"  - Message: {err['message'][:200]}")

    if error_context.get("test_command"):
        lines.append(f"\n**Test command:** `{error_context['test_command']}`")
    if error_context.get("exit_code") is not None:
        lines.append(f"**Exit code:** {error_context['exit_code']}")

    if error_context.get("changed_files"):
        files = ", ".join(f"`{f}`" for f in error_context["changed_files"][:10])
        lines.append(f"**Changed files:** {files}")

    stderr = error_context.get("stderr_tail")
    if stderr:
        snippet = stderr.strip()[:300]
        lines.append(f"\n```\n{snippet}\n```")

    return "\n".join(lines)


def _render_prior_attempts(cycles: list[dict]) -> str:
    if not cycles:
        return ""

    lines = ["\n## Prior Attempts (This Worktree)"]
    for c in cycles:
        err = (c.get("trigger_error") or "unknown")[:120]
        outcome = c.get("outcome") or "unknown"
        dur = c.get("duration_seconds")
        dur_str = f", {dur}s" if dur else ""
        lines.append(f"- Cycle {c['cycle_number']}: {err} -> outcome: **{outcome}**{dur_str}")
    return "\n".join(lines)


def _render_checkpoint(checkpoint: dict | None) -> str:
    if not checkpoint:
        return ""

    lines = ["\n## Last Checkpoint"]
    if checkpoint.get("git_sha"):
        lines.append(f"- Git SHA: `{checkpoint['git_sha']}`")
    if checkpoint.get("label"):
        lines.append(f"- Label: {checkpoint['label']}")

    snapshot = checkpoint.get("artifact_snapshot")
    if isinstance(snapshot, list) and snapshot:
        file_list = ", ".join(f"`{f}`" for f in snapshot[:10])
        suffix = f" (+{len(snapshot) - 10} more)" if len(snapshot) > 10 else ""
        lines.append(f"- Files: {file_list}{suffix}")

    test_results = checkpoint.get("test_results")
    if isinstance(test_results, dict):
        lines.append(f"- Tests: {json.dumps(test_results)}")

    return "\n".join(lines)


def _render_similar_errors(similar: list[dict]) -> str:
    if not similar:
        return ""

    lines = ["\n## Similar Errors (Other Worktrees)"]
    for row in similar[:5]:
        wt_id = row.get("worktree_id", "?")
        err = (row.get("trigger_error") or "")[:120]
        outcome = row.get("outcome") or "?"
        lines.append(f"- Worktree #{wt_id}: {err} (outcome: {outcome})")
    return "\n".join(lines)


def generate_correction_brief(
    db: SessionDB,
    worktree_id: int,
    cycle_number: int,
    trigger_error: str,
    error_context: dict | None = None,
    project: str | None = None,
) -> str:
    """Generate a correction brief for injection into CLAUDE.md.

    Combines:
    1. The trigger error and structured error context
    2. Prior correction cycles for this worktree
    3. The last checkpoint state
    4. Similar errors from other worktrees (via FTS)
    5. Optionally, a slim project brief from brief.py
    """
    prior_cycles = db.get_correction_cycles(worktree_id)
    checkpoint = db.get_latest_checkpoint(worktree_id)

    fts_query = _extract_fts_tokens(trigger_error)
    similar: list[dict] = []
    try:
        similar = db.search_correction_errors(fts_query, limit=5)
    except Exception:
        pass
    similar = [s for s in similar if s.get("worktree_id") != worktree_id]

    sections = [f"# Correction Brief (Cycle {cycle_number} of max {MAX_CORRECTION_CYCLES})"]

    sections.append(f"\n## Current Error\n{trigger_error}")
    sections.append(_render_error_context(error_context))
    sections.append(_render_prior_attempts(prior_cycles))
    sections.append(_render_checkpoint(checkpoint))
    sections.append(_render_similar_errors(similar))

    if project:
        try:
            from engram.brief import generate_slim_brief
            slim = generate_slim_brief(db, project)
            if slim:
                sections.append(f"\n## Project Context\n{slim}")
        except Exception:
            pass

    sections.append(
        "\n## Instructions\n"
        "- Do NOT repeat the approaches from prior cycles — they failed.\n"
        "- Focus on the structured error context to identify root cause.\n"
        "- If the error is in a test file, check the implementation it tests.\n"
        f"- If this is cycle {MAX_CORRECTION_CYCLES} (max), consider escalating with a clear explanation."
    )

    return "\n".join(s for s in sections if s).rstrip() + "\n"


def inject_correction_brief(
    worktree_path: str | os.PathLike,
    brief_content: str,
    cycle_number: int,
) -> dict:
    """Append correction brief to worktree CLAUDE.md.

    Uses a CORRECTION marker instead of the AB marker from ab_brief.py.
    Creates CLAUDE.md if it doesn't exist.
    """
    wt_path = Path(worktree_path)
    claude_md = wt_path / "CLAUDE.md"
    claude_md.parent.mkdir(parents=True, exist_ok=True)
    existed_before = claude_md.exists()

    marker = f"\n\n<!-- ENGRAM_CORRECTION_BRIEF:cycle_{cycle_number} -->\n"
    payload = f"{marker}{brief_content.rstrip()}\n"

    if existed_before:
        existing = claude_md.read_text(encoding="utf-8")
        claude_md.write_text(existing + payload, encoding="utf-8")
    else:
        claude_md.write_text(payload.lstrip("\n"), encoding="utf-8")

    return {
        "claude_md": str(claude_md),
        "cycle_number": cycle_number,
        "appended": existed_before,
    }
