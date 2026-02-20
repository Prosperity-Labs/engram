"""CLI entry point for Engram."""

from __future__ import annotations

import argparse
import json
import sys


def cmd_install(args: argparse.Namespace) -> None:
    """Index all existing sessions into the knowledge base."""
    from pathlib import Path
    from .recall.session_db import SessionDB
    from .adapters.claude_code import ClaudeCodeAdapter

    db = SessionDB()
    adapter = ClaudeCodeAdapter()
    session_paths = adapter.discover_sessions()

    if not session_paths:
        print("No session files found.")
        print("Start using Claude Code to generate sessions, then run this again.")
        return

    sessions = [Path(p) for p in session_paths]
    print(f"Found {len(sessions)} session files")
    print(f"Database: {db.db_path}\n")

    indexed = 0
    skipped = 0
    total_messages = 0

    for i, filepath in enumerate(sessions, 1):
        session_id = filepath.stem
        size_kb = filepath.stat().st_size / 1024

        if db.is_indexed(session_id):
            skipped += 1
            print(f"  [{i}/{len(sessions)}] {session_id[:12]}...  {size_kb:>7.0f} KB  (already indexed)")
            continue

        try:
            result = db.index_session(filepath)
            msg_count = result["messages_indexed"]
            total_messages += msg_count
            indexed += 1
            print(f"  [{i}/{len(sessions)}] {session_id[:12]}...  {size_kb:>7.0f} KB  -> {msg_count} messages")
        except Exception as e:
            print(f"  [{i}/{len(sessions)}] {session_id[:12]}...  ERROR: {e}")

    print(f"\nDone: {indexed} sessions indexed ({total_messages} messages), {skipped} already indexed")

    stats = db.stats()
    print(f"\nKnowledge base: {stats['total_sessions']} sessions, {stats['total_messages']} messages, {stats['db_size_bytes'] / 1024:.0f} KB")


def cmd_monitor(args: argparse.Namespace) -> None:
    """Show knowledge base stats, optionally watch with live indexing."""
    from .monitor import snapshot, render, watch

    if args.watch:
        watch(interval=args.interval, live_index=not args.no_live)
    else:
        snap = snapshot()
        print("Engram Knowledge Base")
        print("=" * 40)
        print(render(snap))


def cmd_search(args: argparse.Namespace) -> None:
    """Search across all indexed sessions."""
    from .recall.session_db import SessionDB

    db = SessionDB()
    query = " ".join(args.query)

    results = db.search(
        query,
        limit=args.limit,
        role=args.role,
        session_id=args.session,
    )

    if not results:
        print(f"No results for: {query}")
        return

    print(f"Found {len(results)} results for: {query}\n")

    for i, r in enumerate(results, 1):
        proj = r["project"] or "?"
        sid = r["session_id"][:12]
        role = r["role"]
        tool = f" [{r['tool_name']}]" if r["tool_name"] else ""
        ts = r["timestamp"] or ""

        # Show snippet with >>> <<< highlights replaced with terminal bold
        snippet = r["snippet"]
        snippet = snippet.replace(">>>", "\033[1;33m").replace("<<<", "\033[0m")

        print(f"  {i}. [{proj}] {sid}  {role}{tool}  {ts}")
        print(f"     {snippet}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="engram",
        description="Engram - Claude Code session knowledge base",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # install
    p_install = subparsers.add_parser("install", help="Index all existing Claude Code sessions")
    p_install.set_defaults(func=cmd_install)

    # monitor
    p_mon = subparsers.add_parser("monitor", help="Knowledge base stats and live indexing")
    p_mon.add_argument("--watch", "-w", action="store_true", help="Continuous monitoring mode")
    p_mon.add_argument("--interval", type=int, default=10, help="Poll interval in seconds (default: 10)")
    p_mon.add_argument("--no-live", action="store_true", help="Disable live session indexing")
    p_mon.set_defaults(func=cmd_monitor)

    # search
    p_search = subparsers.add_parser("search", help="Full-text search across all sessions")
    p_search.add_argument("query", nargs="+", help="Search query (supports AND, OR, NOT, \"phrases\", prefix*)")
    p_search.add_argument("--limit", "-n", type=int, default=20, help="Max results (default: 20)")
    p_search.add_argument("--role", choices=["user", "assistant", "summary"], help="Filter by role")
    p_search.add_argument("--session", help="Filter to a specific session ID")
    p_search.set_defaults(func=cmd_search)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
