#!/usr/bin/env python3
"""Git post-commit hook: writes a checkpoint row to sessions.db.

Captures git_sha from HEAD and artifact_snapshot from the committed files.

Install into a worktree's .git/hooks/post-commit (or use with git's
core.hooksPath). Expects LOOPWRIGHT_WORKTREE_ID and optionally
LOOPWRIGHT_SESSION_ID as environment variables.

Usage as a standalone script:
    LOOPWRIGHT_WORKTREE_ID=1 python -m engram.hooks.loopwright_post_commit

Usage as a git hook (symlink or copy to .git/hooks/post-commit):
    #!/bin/sh
    export LOOPWRIGHT_WORKTREE_ID=1
    exec python -m engram.hooks.loopwright_post_commit
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def get_head_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def get_committed_files() -> list[str]:
    """Files changed in the most recent commit."""
    try:
        result = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return [f for f in result.stdout.strip().split("\n") if f]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []


def get_commit_message() -> str | None:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def main() -> int:
    worktree_id = os.environ.get("LOOPWRIGHT_WORKTREE_ID")
    if not worktree_id:
        return 0

    try:
        worktree_id_int = int(worktree_id)
    except ValueError:
        print(f"loopwright post-commit: invalid LOOPWRIGHT_WORKTREE_ID={worktree_id!r}",
              file=sys.stderr)
        return 1

    session_id = os.environ.get("LOOPWRIGHT_SESSION_ID")
    ab_variant_label = os.environ.get("LOOPWRIGHT_AB_VARIANT")
    git_sha = get_head_sha()
    committed_files = get_committed_files()
    commit_msg = get_commit_message()

    from engram.recall.session_db import SessionDB

    db = SessionDB()
    label = commit_msg[:80] if commit_msg else None
    checkpoint_id = db.create_checkpoint(
        worktree_id_int,
        session_id=session_id,
        git_sha=git_sha,
        artifact_snapshot=committed_files,
        ab_variant_label=ab_variant_label,
        label=label,
    )

    print(f"loopwright: checkpoint {checkpoint_id} created (sha={git_sha[:8] if git_sha else '?'},"
          f" {len(committed_files)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
