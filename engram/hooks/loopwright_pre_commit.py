#!/usr/bin/env python3
"""Git pre-commit hook: captures the staged diff as a snapshot.

Writes a JSON file to /tmp/loopwright-pre-commit-snapshot.json containing
the staged diff and list of staged files. The post-commit hook or agent
can pick this up to enrich checkpoint data.

Expects LOOPWRIGHT_WORKTREE_ID env var to activate. If unset, exits silently.

Usage as a git hook (symlink or copy to .git/hooks/pre-commit):
    #!/bin/sh
    export LOOPWRIGHT_WORKTREE_ID=1
    exec python -m engram.hooks.loopwright_pre_commit
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


SNAPSHOT_PATH = Path("/tmp/loopwright-pre-commit-snapshot.json")


def get_staged_files() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return [f for f in result.stdout.strip().split("\n") if f]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []


def get_staged_diff() -> str:
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--stat"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def get_current_branch() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def main() -> int:
    worktree_id = os.environ.get("LOOPWRIGHT_WORKTREE_ID")
    if not worktree_id:
        return 0

    staged_files = get_staged_files()
    diff_stat = get_staged_diff()
    branch = get_current_branch()

    snapshot = {
        "worktree_id": worktree_id,
        "session_id": os.environ.get("LOOPWRIGHT_SESSION_ID"),
        "branch": branch,
        "staged_files": staged_files,
        "diff_stat": diff_stat,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2))
    print(f"loopwright: pre-commit snapshot saved ({len(staged_files)} staged files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
