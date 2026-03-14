"""CLI entry point for enrichment — called by Bun proxy via subprocess.

Usage: python3 -m engram.proxy.enrichment_cli <project_name>
Prints enrichment block to stdout, or nothing if unavailable.
"""

from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(1)

    project = sys.argv[1]

    try:
        from engram.proxy.enrichment import build_enrichment
        from engram.recall.session_db import SessionDB

        db = SessionDB()
        result = build_enrichment(project, db)
        if result:
            print(result)
    except Exception:
        pass  # enrichment failure is silent


if __name__ == "__main__":
    main()
