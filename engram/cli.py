"""CLI entry point for Engram."""

from __future__ import annotations

import argparse
import json
import sys


def _short_project(name: str | None) -> str:
    """Shorten Claude Code project paths to readable names."""
    if not name:
        return "?"
    from .recall.session_db import clean_project_name
    return clean_project_name(name)


def cmd_install(args: argparse.Namespace) -> None:
    """Index all existing sessions into the knowledge base."""
    from pathlib import Path
    from .recall.session_db import SessionDB
    from .adapters.claude_code import ClaudeCodeAdapter
    from .adapters.codex import CodexAdapter

    db = SessionDB()
    claude_adapter = ClaudeCodeAdapter()
    codex_adapter = CodexAdapter()

    all_sessions = []
    for path in claude_adapter.discover_sessions():
        all_sessions.append(("claude_code", path))
    for path in codex_adapter.discover_sessions():
        all_sessions.append(("codex", path))

    # Try Cursor too if available
    try:
        from .adapters.cursor import CursorAdapter
        cursor_adapter = CursorAdapter()
        for path in cursor_adapter.discover_sessions():
            all_sessions.append(("cursor", path))
    except ImportError:
        pass

    if not all_sessions:
        print("No session files found.")
        print("Start using Claude Code, Codex, or Cursor to generate sessions, then run this again.")
        return

    sessions = [(agent, Path(p)) for agent, p in all_sessions]
    print(f"Found {len(sessions)} session files")
    print(f"Database: {db.db_path}\n")

    indexed = 0
    skipped = 0
    total_messages = 0

    for i, (agent, filepath) in enumerate(sessions, 1):
        session_id = filepath.stem
        size_kb = filepath.stat().st_size / 1024

        if db.is_indexed(session_id):
            skipped += 1
            print(f"  [{i}/{len(sessions)}] {session_id[:12]}...  {size_kb:>7.0f} KB  (already indexed)")
            continue

        try:
            if agent == "claude_code":
                session = claude_adapter.parse_file(str(filepath))
            elif agent == "codex":
                session = codex_adapter.parse_file(str(filepath))
            elif agent == "cursor":
                from .adapters.cursor import CursorAdapter

                cursor_adapter = CursorAdapter()
                session = cursor_adapter.parse_file(str(filepath))
            else:
                raise ValueError(f"Unknown agent: {agent}")

            result = db.index_from_session(session, filepath)
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


def _sanitize_fts_query(raw: str) -> str:
    """Sanitize user input for FTS5 MATCH queries.

    FTS5 treats characters like -, *, ^, : as operators.
    Wrap each token in double quotes so they're treated as literals.
    Preserves user-quoted phrases like "exact match".
    """
    import re
    parts = []
    for segment in re.split(r'(".*?")', raw):
        if segment.startswith('"') and segment.endswith('"'):
            parts.append(segment)
        else:
            for tok in segment.split():
                escaped = tok.replace('"', '""')
                parts.append(f'"{escaped}"')
    return " ".join(parts)


def cmd_search(args: argparse.Namespace) -> None:
    """Search across all indexed sessions."""
    from .recall.session_db import SessionDB

    db = SessionDB()
    query = _sanitize_fts_query(" ".join(args.query))

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


def cmd_costs(args: argparse.Namespace) -> None:
    """Show estimated costs per session."""
    from .recall.session_db import SessionDB

    db = SessionDB()
    costs = db.session_costs(limit=args.limit)

    if not costs:
        print("No sessions indexed. Run `engram install` first.")
        return

    print(f"{'Session':>18} | {'Project':>20} | {'Msgs':>6} | {'Input':>10} | {'Cache Read':>12} | {'Cache Create':>12} | {'Output':>8} | {'Cost':>8}")
    print("-" * 115)
    total = 0.0
    for c in costs:
        proj = (c["project"] or "?")[:20]
        sid = c["session_id"][:16]
        has_cache = c["cache_read_tokens"] > 0
        marker = "" if has_cache else "*"
        print(
            f"  {sid}.. | {proj:>20} | {c['message_count']:>6} | "
            f"{c['input_tokens']:>10,} | {c['cache_read_tokens']:>12,} | "
            f"{c['cache_create_tokens']:>12,} | {c['output_tokens']:>8,} | "
            f"${c['estimated_cost']:>7.2f}{marker}"
        )
        total += c["estimated_cost"]

    print(f"\nTotal: ${total:.2f}")
    if any(c["cache_read_tokens"] == 0 and c["input_tokens"] > 0 for c in costs):
        print("\n* = needs re-index for accurate cost (run `engram reindex`)")


def cmd_insights(args: argparse.Namespace) -> None:
    """Show analytics across all indexed sessions."""
    from .recall.session_db import SessionDB

    db = SessionDB()
    data = db.insights()

    if args.json:
        import json as _json
        print(_json.dumps(data, indent=2, default=str))
        return

    stats = db.stats()
    print("Engram Insights")
    print("=" * 50)
    print(f"{stats['total_sessions']} sessions | {stats['total_messages']} messages | {stats['db_size_bytes'] / 1024:.0f} KB\n")

    # Cache efficiency
    ce = data["cache_efficiency"]
    print("Cache Efficiency")
    print("-" * 40)
    print(f"  Cache read:    {ce['cache_read_pct']}% of input tokens")
    print(f"  Actual cost:   ${ce['cost_actual']:,.2f}")
    print(f"  Without cache: ${ce['cost_without_cache']:,.2f}")
    print(f"  Saved:         ${ce['savings']:,.2f} ({ce['savings_pct']}%)")
    print()

    # Tool usage
    if data["tool_usage"]:
        print("Top Tools")
        print("-" * 40)
        max_count = data["tool_usage"][0]["count"]
        for t in data["tool_usage"][:10]:
            bar_len = int(t["count"] / max_count * 20)
            bar = "#" * bar_len
            print(f"  {t['tool']:>15}  {bar}  {t['count']}")
        print()

    # Projects
    if data["projects"]:
        print("Projects")
        print("-" * 40)
        for p in data["projects"][:8]:
            name = _short_project(p["project"])
            print(f"  {name[:30]:<30}  {p['sessions']:>3} sessions  {p['messages']:>5} msgs")
        print()

    # Role breakdown
    rb = data["role_breakdown"]
    if rb:
        print("Messages by Role")
        print("-" * 40)
        for role, count in rb.items():
            print(f"  {role:<12} {count:>8,}")
        print()

    # Hourly activity
    hourly = data["hourly_activity"]
    if hourly:
        print("Coding Hours (sessions started)")
        print("-" * 40)
        max_h = max(hourly.values()) if hourly else 1
        for h in range(24):
            c = hourly.get(h, 0)
            if c > 0:
                bar = "#" * int(c / max_h * 20)
                print(f"  {h:02d}:00  {bar}  {c}")
        print()

    # Expensive sessions
    if data["expensive_sessions"]:
        print("Most Expensive (per message)")
        print("-" * 40)
        for e in data["expensive_sessions"][:5]:
            proj = _short_project(e["project"])[:20]
            print(f"  {e['session_id'][:12]}..  {proj:<20}  {e['messages']:>4} msgs  ${e['total_cost']:>7.2f}  (${e['cost_per_msg']:.3f}/msg)")
        print()

    # Error sessions
    if data["error_sessions"]:
        print("Error-Heavy Sessions")
        print("-" * 40)
        for e in data["error_sessions"][:5]:
            proj = _short_project(e["project"])[:20]
            print(f"  {e['session_id'][:12]}..  {proj:<20}  {e['error_messages']:>3} errors / {e['total_messages']} msgs ({e['error_pct']}%)")
        print()

    # Topics
    topics = data["topics"]
    if topics:
        sorted_topics = sorted(topics.items(), key=lambda x: x[1], reverse=True)
        nonzero = [(k, v) for k, v in sorted_topics if v > 0]
        if nonzero:
            print("Topics (sessions mentioning)")
            print("-" * 40)
            for kw, count in nonzero:
                print(f"  {kw:<15} {count:>4} sessions")
            print()


def cmd_stats(args: argparse.Namespace) -> None:
    """Show per-project analytics."""
    from .recall.session_db import SessionDB
    from .stats import compute_project_stats, compute_session_stats, render_project_stats

    db = SessionDB()

    if args.session:
        s = compute_session_stats(db, args.session)
        print(render_project_stats([s]))
    else:
        stats = compute_project_stats(db)
        if args.project:
            stats = [s for s in stats if s["project"] == args.project]
        if not stats:
            print("No stats found. Run `engram install` first.")
            return
        print(render_project_stats(stats))


def cmd_sessions(args: argparse.Namespace) -> None:
    """List sessions with filtering and sorting."""
    from .recall.session_db import SessionDB
    from .sessions import list_sessions, render_sessions

    db = SessionDB()
    sessions = list_sessions(
        db,
        project=args.project,
        min_messages=args.min_messages,
        sort_by=args.sort,
        limit=args.limit,
    )

    if not sessions:
        print("No sessions found. Run `engram install` first.")
        return

    print(render_sessions(sessions))


def cmd_artifacts(args: argparse.Namespace) -> None:
    """Extract and query artifacts from indexed sessions."""
    from .recall.session_db import SessionDB
    from .recall.artifact_extractor import ArtifactExtractor

    db = SessionDB()
    extractor = ArtifactExtractor(db)

    if args.extract:
        result = extractor.extract_all()
        print(f"Processed {result['sessions_processed']} sessions, extracted {result['artifacts_extracted']} artifacts")
        return

    if args.session:
        summary = extractor.summary(args.session)
        print(f"Session {args.session[:12]}...")
        print(f"  Files read:    {summary['files_read']}")
        print(f"  Files written: {summary['files_written']}")
        print(f"  Files created: {summary['files_created']}")
        print(f"  Commands:      {summary['commands']}")
        print(f"  API calls:     {summary['api_calls']}")
        print(f"  Errors:        {summary['errors']}")
        if summary['top_files']:
            print(f"\n  Top files:")
            for path, count in summary['top_files'][:10]:
                print(f"    {count:>3}x  {path}")
        if summary['top_commands']:
            print(f"\n  Top commands:")
            for cmd, count in summary['top_commands'][:10]:
                print(f"    {count:>3}x  {cmd[:80]}")
        return

    artifacts = extractor.get_artifacts(
        project=args.project,
        artifact_type=args.type,
        limit=args.limit,
    )
    if not artifacts:
        print("No artifacts found. Run `engram artifacts --extract` first.")
        return

    for a in artifacts:
        sid = a['session_id'][:8]
        print(f"  [{sid}..] {a['artifact_type']:<12} {a['target'][:80]}")


def cmd_export(args: argparse.Namespace) -> None:
    """Export session data to JSON or CSV."""
    from .recall.session_db import SessionDB
    from .export import export_events, export_sessions

    db = SessionDB()

    if args.sessions_only:
        result = export_sessions(db, format=args.format, output=args.output)
    else:
        result = export_events(
            db,
            format=args.format,
            project=args.project,
            session_id=args.session,
            output=args.output,
        )

    if args.output:
        print(f"Exported to {args.output}")
    else:
        print(result)


def cmd_clean_names(args: argparse.Namespace) -> None:
    """Clean up raw project directory names in the database."""
    from .recall.session_db import SessionDB

    db = SessionDB()
    count = db.clean_all_project_names()
    if count == 0:
        print("All project names are already clean.")
    else:
        print(f"Updated {count} project names.")


def cmd_brief(args: argparse.Namespace) -> None:
    """Generate a project brief from session history."""
    from .recall.session_db import SessionDB
    from .brief import generate_brief

    db = SessionDB()

    project = args.project
    if not project:
        with db._connect() as conn:
            projects = [
                row["project"]
                for row in conn.execute(
                    """SELECT project, COUNT(*) as cnt
                       FROM sessions
                       WHERE project IS NOT NULL
                       GROUP BY project
                       ORDER BY cnt DESC
                       LIMIT 1"""
                ).fetchall()
            ]
        if projects:
            project = projects[0]
        else:
            print("No projects found. Run `engram install` first.")
            return

    result = generate_brief(db, project=project, format=args.format)

    if args.output:
        from pathlib import Path
        Path(args.output).write_text(result)
        print(f"Brief written to {args.output}")
    else:
        print(result)


def cmd_reindex(args: argparse.Namespace) -> None:
    """Re-index all sessions to backfill granular token data."""
    from pathlib import Path
    from .recall.session_db import SessionDB
    from .adapters.claude_code import ClaudeCodeAdapter

    db = SessionDB()
    adapter = ClaudeCodeAdapter()
    sessions = adapter.discover_sessions()

    print(f"Re-indexing {len(sessions)} sessions for granular token tracking...")
    reindexed = 0
    errors = 0

    for i, filepath_str in enumerate(sessions, 1):
        filepath = Path(filepath_str)
        session_id = filepath.stem
        size_kb = filepath.stat().st_size / 1024
        try:
            result = db.index_session(filepath)
            reindexed += 1
            if i % 20 == 0 or i == len(sessions):
                print(f"  [{i}/{len(sessions)}] {reindexed} re-indexed, {errors} errors")
        except Exception as e:
            errors += 1

    print(f"\nDone: {reindexed} re-indexed, {errors} errors")
    print("Run `engram costs` to see accurate cost breakdown.")


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

    # costs
    p_costs = subparsers.add_parser("costs", help="Show estimated token costs per session")
    p_costs.add_argument("--limit", "-n", type=int, default=10, help="Number of sessions to show (default: 10)")
    p_costs.set_defaults(func=cmd_costs)

    # insights
    p_insights = subparsers.add_parser("insights", help="Analytics dashboard across all sessions")
    p_insights.add_argument("--json", action="store_true", help="Output raw JSON instead of formatted text")
    p_insights.set_defaults(func=cmd_insights)

    # stats
    p_stats = subparsers.add_parser("stats", help="Per-project analytics (tokens, errors, tool usage)")
    p_stats.add_argument("--project", "-p", help="Filter to a specific project")
    p_stats.add_argument("--session", "-s", help="Stats for a single session")
    p_stats.set_defaults(func=cmd_stats)

    # sessions
    p_sessions = subparsers.add_parser("sessions", help="List sessions with filtering")
    p_sessions.add_argument("--project", "-p", help="Filter by project name")
    p_sessions.add_argument("--sort", choices=["recent", "messages", "tokens"], default="recent", help="Sort order (default: recent)")
    p_sessions.add_argument("--min-messages", type=int, default=0, help="Minimum message count")
    p_sessions.add_argument("--limit", "-n", type=int, default=20, help="Max results (default: 20)")
    p_sessions.set_defaults(func=cmd_sessions)

    # artifacts
    p_artifacts = subparsers.add_parser("artifacts", help="Extract and query tool artifacts")
    p_artifacts.add_argument("--extract", action="store_true", help="Run extraction on all sessions")
    p_artifacts.add_argument("--session", "-s", help="Show artifact summary for a session")
    p_artifacts.add_argument("--project", "-p", help="Filter by project")
    p_artifacts.add_argument("--type", "-t", choices=["file_read", "file_write", "file_create", "command", "api_call", "error"], help="Filter by artifact type")
    p_artifacts.add_argument("--limit", "-n", type=int, default=20, help="Max results (default: 20)")
    p_artifacts.set_defaults(func=cmd_artifacts)

    # export
    p_export = subparsers.add_parser("export", help="Export data to JSON or CSV")
    p_export.add_argument("--format", "-f", choices=["json", "csv"], default="json", help="Output format (default: json)")
    p_export.add_argument("--sessions-only", action="store_true", help="Export session metadata only (no messages)")
    p_export.add_argument("--project", "-p", help="Filter by project")
    p_export.add_argument("--session", "-s", help="Filter to a single session")
    p_export.add_argument("--output", "-o", help="Write to file instead of stdout")
    p_export.set_defaults(func=cmd_export)

    # clean-names
    p_clean = subparsers.add_parser("clean-names", help="Clean up raw project directory names")
    p_clean.set_defaults(func=cmd_clean_names)

    # reindex
    p_reindex = subparsers.add_parser("reindex", help="Re-index all sessions (backfills granular token data)")
    p_reindex.set_defaults(func=cmd_reindex)

    # brief
    p_brief = subparsers.add_parser("brief", help="Generate project brief from session history")
    p_brief.add_argument("--project", "-p", help="Project name (auto-detects if omitted)")
    p_brief.add_argument("--format", "-f", choices=["markdown", "json"], default="markdown",
                          help="Output format (default: markdown)")
    p_brief.add_argument("--output", "-o", help="Write to file instead of stdout")
    p_brief.set_defaults(func=cmd_brief)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
