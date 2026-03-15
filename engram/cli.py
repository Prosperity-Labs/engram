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

    quiet = getattr(args, "quiet", False)
    log = (lambda *a, **kw: None) if quiet else print

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
        log("No session files found.")
        log("Start using Claude Code, Codex, or Cursor to generate sessions, then run this again.")
        return

    sessions = [(agent, Path(p)) for agent, p in all_sessions]
    log(f"Found {len(sessions)} session files")
    log(f"Database: {db.db_path}\n")

    indexed = 0
    skipped = 0
    total_messages = 0

    for i, (agent, filepath) in enumerate(sessions, 1):
        session_id = filepath.stem
        size_kb = filepath.stat().st_size / 1024

        if db.is_indexed(session_id):
            skipped += 1
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
            log(f"  [{i}/{len(sessions)}] {session_id[:12]}...  {size_kb:>7.0f} KB  -> {msg_count} messages")
        except Exception as e:
            log(f"  [{i}/{len(sessions)}] {session_id[:12]}...  ERROR: {e}")

    log(f"\nDone: {indexed} sessions indexed ({total_messages} messages), {skipped} already indexed")

    # Auto-extract artifacts so hooks have data to work with
    from .recall.artifact_extractor import ArtifactExtractor
    extractor = ArtifactExtractor(db)
    log("\nExtracting artifacts...")
    result = extractor.extract_all()
    log(f"Artifacts: {result['artifacts_extracted']} extracted from {result['sessions_processed']} sessions")

    stats = db.stats()
    log(f"\nKnowledge base: {stats['total_sessions']} sessions, {stats['total_messages']} messages, {stats['db_size_bytes'] / 1024:.0f} KB")

    # Auto-wire MCP server
    from .install_mcp import install_mcp_global
    mcp_result = install_mcp_global()
    if mcp_result["already_existed"]:
        log(f"  MCP server: already configured in {mcp_result['path']}")
    else:
        log(f"  MCP server: registered in {mcp_result['path']}")


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


def cmd_embed(args: argparse.Namespace) -> None:
    """Backfill semantic embeddings for all indexed messages."""
    from .recall.session_db import SessionDB
    from .recall import vector_search

    if not vector_search.is_available():
        print("Semantic dependencies are not installed. Run: pip install -e '.[semantic]'")
        return

    db = SessionDB()
    batch_size = 64

    with db._connect() as conn:
        vector_search.init_vec_table(conn)

        total_messages = conn.execute(
            "SELECT COUNT(*) AS c FROM messages"
        ).fetchone()["c"]

        try:
            rows = conn.execute(
                """
                SELECT m.id AS message_id, m.content
                FROM messages m
                LEFT JOIN vec_messages v ON v.message_id = m.id
                WHERE m.content IS NOT NULL
                  AND TRIM(m.content) != ''
                  AND v.message_id IS NULL
                ORDER BY m.id
                """
            ).fetchall()
        except Exception:
            print("Vector table is unavailable in this SQLite build.")
            return

        pending = [dict(row) for row in rows]
        total_pending = len(pending)

        if total_pending == 0:
            print("No pending messages to embed.")
            print(f"Total messages: {total_messages} | Embedded this run: 0")
            return

        embedded = 0
        for start in range(0, total_pending, batch_size):
            end = min(start + batch_size, total_pending)
            embedded += vector_search.index_message_vectors(conn, pending[start:end])
            print(f"Embedding messages... {end}/{total_pending}")

    print(f"Done. Embedded {embedded} messages.")
    print(f"Total messages: {total_messages} | Pending at start: {total_pending}")


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

    result = generate_brief(db, project=project, format=args.format, slim=args.slim)

    if args.output:
        from pathlib import Path
        Path(args.output).write_text(result)
        print(f"Brief written to {args.output}")
    else:
        print(result)


def cmd_hooks_install(args: argparse.Namespace) -> None:
    """Install Engram hooks into Claude Code settings."""
    from .hooks import install_hook

    scope = "project" if args.project else "global"
    auto_brief = getattr(args, "auto_brief", False)
    result = install_hook(scope=scope, auto_brief=auto_brief)
    print(result)


def cmd_hook_handle(args: argparse.Namespace) -> None:
    """Handle a PreToolUse hook call from Claude Code (reads JSON from stdin)."""
    from .hooks import handle_pretool_hook

    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return
        stdin_json = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        return

    result = handle_pretool_hook(stdin_json)
    if result:
        print(json.dumps(result))


def cmd_mcp_install(args: argparse.Namespace) -> None:
    """Register engram MCP server with Claude Code."""
    from .install_mcp import install_mcp_global, install_mcp_project

    if args.project_dir:
        result = install_mcp_project(args.project_dir)
    else:
        result = install_mcp_global()

    if result["already_existed"]:
        print(f"Engram MCP already configured in {result['path']}")
    else:
        print(f"Engram MCP server registered in {result['path']}")
        print("Restart Claude Code to activate.")


def cmd_mcp(args: argparse.Namespace) -> None:
    """Start the Engram MCP server (stdio transport)."""
    from engram.mcp_server import server
    server.run()


def cmd_graph_load(args: argparse.Namespace) -> None:
    """Load Engram data into Memgraph knowledge graph."""
    try:
        from engram.graph import GraphLoader, get_driver
    except ImportError:
        print("Graph dependencies not installed. Run: pip install -e '.[graph]'")
        sys.exit(1)

    try:
        driver = get_driver(args.bolt_uri)
        driver.verify_connectivity()
    except Exception as e:
        print(f"Cannot connect to Memgraph at {args.bolt_uri}: {e}")
        print("Start Memgraph: docker run -d --name engram-memgraph -p 7687:7687 memgraph/memgraph-mage:latest")
        sys.exit(1)

    loader = GraphLoader(driver, db_path=args.db_path)
    print(f"Loading graph from {loader.db_path}...")

    counts = loader.load_all(project=args.project)
    driver.close()

    print("\nGraph loaded:")
    for label, count in counts.items():
        print(f"  {label}: {count}")
    print(f"\nTotal: {sum(counts.values())} nodes/edges created or updated")


def cmd_graph_algo(args: argparse.Namespace) -> None:
    """Run graph algorithms on the Memgraph knowledge graph."""
    try:
        from engram.graph import get_driver
        from engram.graph.algorithms import run_algorithms
    except ImportError:
        print("Graph dependencies not installed. Run: pip install -e '.[graph]'")
        sys.exit(1)

    try:
        driver = get_driver(args.bolt_uri)
        driver.verify_connectivity()
    except Exception as e:
        print(f"Cannot connect to Memgraph at {args.bolt_uri}: {e}")
        sys.exit(1)

    results = run_algorithms(driver, algorithm=args.algorithm)
    driver.close()

    print(json.dumps(results, indent=2, default=str))


def cmd_proxy_start(args: argparse.Namespace) -> None:
    """Start the Engram proxy server."""
    from engram.proxy.start import start_proxy
    start_proxy(
        port=args.port, verbose=args.verbose, enrich=not args.no_enrich,
        timeout=args.timeout, max_concurrent=args.max_concurrent,
        max_buffer_mb=args.max_buffer_mb,
    )


def cmd_proxy_install(args: argparse.Namespace) -> None:
    """Install engram proxy as a systemd user service."""
    import shutil
    from pathlib import Path

    bun_bin = shutil.which("bun")
    if not bun_bin:
        print("ERROR: bun not found in PATH. Install: https://bun.sh", file=sys.stderr)
        sys.exit(1)

    server_ts = Path(__file__).parent / "proxy" / "bun" / "server.ts"
    if not server_ts.exists():
        print(f"ERROR: server.ts not found at {server_ts}", file=sys.stderr)
        sys.exit(1)

    port = args.port
    service_name = "engram-proxy"

    unit = f"""\
[Unit]
Description=Engram Proxy — AI agent API call interceptor
After=network.target

[Service]
Type=simple
ExecStart={bun_bin} run {server_ts} --port {port}
WorkingDirectory={server_ts.parent.parent.parent.parent}
Restart=on-failure
RestartSec=5
Environment=HOME={Path.home()}
Environment=PATH={Path(bun_bin).parent}:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=default.target
"""

    systemd_dir = Path.home() / ".config" / "systemd" / "user"
    systemd_dir.mkdir(parents=True, exist_ok=True)
    unit_path = systemd_dir / f"{service_name}.service"
    unit_path.write_text(unit)

    print(f"Wrote {unit_path}")

    # Reload and enable
    import subprocess
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", service_name], check=True)

    if args.now:
        subprocess.run(["systemctl", "--user", "start", service_name], check=True)
        print(f"\n{service_name} started on port {port}.")
    else:
        print(f"\n{service_name} enabled. Start with:")
        print(f"  systemctl --user start {service_name}")

    print(f"\nUsage:")
    print(f"  export ANTHROPIC_BASE_URL=http://localhost:{port}")
    print(f"  systemctl --user status {service_name}")
    print(f"  journalctl --user -u {service_name} -f")


def cmd_proxy_uninstall(args: argparse.Namespace) -> None:
    """Remove engram proxy systemd user service."""
    import subprocess
    from pathlib import Path

    service_name = "engram-proxy"
    unit_path = Path.home() / ".config" / "systemd" / "user" / f"{service_name}.service"

    if not unit_path.exists():
        print(f"{service_name} is not installed.")
        return

    subprocess.run(["systemctl", "--user", "stop", service_name], check=False)
    subprocess.run(["systemctl", "--user", "disable", service_name], check=False)
    unit_path.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    print(f"{service_name} stopped, disabled, and removed.")


def cmd_proxy_metrics(args: argparse.Namespace) -> None:
    """Show session-level metrics and enrichment comparison."""
    from engram.proxy.metrics import backfill, print_comparison, print_recent

    if args.backfill:
        results = backfill()
        print(f"Computed metrics for {len(results)} sessions.")
        print()

    if args.recent:
        print_recent(limit=args.limit)
    else:
        print_comparison()


def cmd_proxy_stats(args: argparse.Namespace) -> None:
    """Show proxy call statistics."""
    import sqlite3
    from pathlib import Path

    db_path = Path.home() / ".config" / "engram" / "sessions.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        row = conn.execute("""
            SELECT COUNT(*) AS calls,
                   COALESCE(SUM(input_tokens), 0) AS total_in,
                   COALESCE(SUM(output_tokens), 0) AS total_out,
                   COALESCE(SUM(cache_read_tokens), 0) AS total_cache_read,
                   COALESCE(SUM(cost_estimate_usd), 0) AS total_cost,
                   MIN(timestamp) AS first_call,
                   MAX(timestamp) AS last_call
            FROM proxy_calls
        """).fetchone()
    except sqlite3.OperationalError:
        print("No proxy data yet. Start the proxy first: engram proxy start")
        return
    finally:
        conn.close()

    if row["calls"] == 0:
        print("No proxy calls recorded yet.")
        return

    print("Engram Proxy Stats")
    print("=" * 40)
    print(f"  Total calls:       {row['calls']:,}")
    print(f"  Input tokens:      {row['total_in']:,}")
    print(f"  Output tokens:     {row['total_out']:,}")
    print(f"  Cache read tokens: {row['total_cache_read']:,}")
    print(f"  Total cost:        ${row['total_cost']:.4f}")
    print(f"  First call:        {row['first_call']}")
    print(f"  Last call:         {row['last_call']}")


def cmd_proxy_calls(args: argparse.Namespace) -> None:
    """Show recent proxy calls."""
    import sqlite3
    from pathlib import Path

    db_path = Path.home() / ".config" / "engram" / "sessions.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute("""
            SELECT timestamp, model, input_tokens, output_tokens,
                   cache_read_tokens, cost_estimate_usd, tools_used,
                   stop_reason, project
            FROM proxy_calls
            ORDER BY timestamp DESC
            LIMIT ?
        """, (args.limit,)).fetchall()
    except sqlite3.OperationalError:
        print("No proxy data yet. Start the proxy first: engram proxy start")
        return
    finally:
        conn.close()

    if not rows:
        print("No proxy calls recorded yet.")
        return

    print(f"Last {len(rows)} proxy calls:")
    print()
    for r in reversed(rows):
        model = (r["model"] or "?").split("-")[-1][:12]
        tools = json.loads(r["tools_used"]) if r["tools_used"] else []
        tools_str = ",".join(tools[:3]) if tools else "-"
        proj = r["project"] or "?"
        print(
            f"  {r['timestamp'][:19]}  {model:<12} "
            f"in={r['input_tokens']:>7,} out={r['output_tokens']:>6,} "
            f"cache={r['cache_read_tokens']:>7,} "
            f"${r['cost_estimate_usd']:.4f} "
            f"[{tools_str}] {proj}"
        )


def cmd_proxy_report(args: argparse.Namespace) -> None:
    """Show enrichment comparison report."""
    from engram.proxy.report import generate_report
    print(generate_report(project=args.project))


def cmd_trail(args: argparse.Namespace) -> None:
    """Show artifact trail for a Claude Code session."""
    from .artifact_trail import parse_session_trail, find_session_jsonl, format_trail

    jsonl_path = find_session_jsonl(args.session_id)
    if not jsonl_path:
        print(f"Session {args.session_id} not found", file=sys.stderr)
        raise SystemExit(1)

    events = parse_session_trail(jsonl_path)
    print(format_trail(events))


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
    p_install.add_argument("--quiet", "-q", action="store_true",
                            help="Suppress output (for use in hooks)")
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

    # embed
    p_embed = subparsers.add_parser("embed", help="Generate semantic embeddings for indexed messages")
    p_embed.set_defaults(func=cmd_embed)

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
    p_brief.add_argument("--slim", action="store_true",
                          help="Generate compact brief (<500 tokens) with only dangerous knowledge")
    p_brief.add_argument("--output", "-o", help="Write to file instead of stdout")
    p_brief.set_defaults(func=cmd_brief)

    # hooks install
    p_hooks = subparsers.add_parser("hooks", help="Manage Claude Code hooks")
    hooks_sub = p_hooks.add_subparsers(dest="hooks_command")
    p_hooks_install = hooks_sub.add_parser("install", help="Install Engram hooks")
    p_hooks_install.add_argument("--project", action="store_true",
                                  help="Install to .claude/settings.json (project scope) instead of global")
    p_hooks_install.add_argument("--auto-brief", action="store_true",
                                  help="Also install SessionStart hook to auto-generate CLAUDE.md")
    p_hooks_install.set_defaults(func=cmd_hooks_install)
    p_hooks.set_defaults(func=lambda args: p_hooks.print_help())

    # proxy
    p_proxy = subparsers.add_parser("proxy", help="Engram proxy — intercept and log AI agent API calls")
    proxy_sub = p_proxy.add_subparsers(dest="proxy_command")
    p_proxy_start = proxy_sub.add_parser("start", help="Start the proxy server")
    p_proxy_start.add_argument("--port", type=int, default=9080, help="Listen port (default: 9080)")
    p_proxy_start.add_argument("--verbose", "-v", action="store_true", help="Show mitmproxy output")
    p_proxy_start.add_argument("--no-enrich", action="store_true", help="Disable system prompt enrichment")
    p_proxy_start.add_argument("--timeout", type=int, default=120, help="Upstream fetch timeout in seconds (default: 120)")
    p_proxy_start.add_argument("--max-concurrent", type=int, default=50, help="Max concurrent /v1/messages requests (default: 50)")
    p_proxy_start.add_argument("--max-buffer-mb", type=int, default=50, help="Max streaming buffer in MB (default: 50)")
    p_proxy_start.set_defaults(func=cmd_proxy_start)
    p_proxy_stats = proxy_sub.add_parser("stats", help="Show proxy call statistics")
    p_proxy_stats.set_defaults(func=cmd_proxy_stats)
    p_proxy_calls = proxy_sub.add_parser("calls", help="Show recent intercepted calls")
    p_proxy_calls.add_argument("--limit", "-n", type=int, default=20, help="Number of calls to show (default: 20)")
    p_proxy_calls.set_defaults(func=cmd_proxy_calls)
    p_proxy_report = proxy_sub.add_parser("report", help="Compare baseline vs. enriched calls")
    p_proxy_report.add_argument("--project", "-p", help="Filter to a specific project")
    p_proxy_report.set_defaults(func=cmd_proxy_report)
    p_proxy_install = proxy_sub.add_parser("install", help="Install proxy as a systemd user service")
    p_proxy_install.add_argument("--port", type=int, default=9080, help="Listen port (default: 9080)")
    p_proxy_install.add_argument("--now", action="store_true", help="Start the service immediately after installing")
    p_proxy_install.set_defaults(func=cmd_proxy_install)
    p_proxy_uninstall = proxy_sub.add_parser("uninstall", help="Remove proxy systemd user service")
    p_proxy_uninstall.set_defaults(func=cmd_proxy_uninstall)
    p_proxy_metrics = proxy_sub.add_parser("metrics", help="Show session-level metrics (enrichment comparison)")
    p_proxy_metrics.add_argument("--backfill", action="store_true", help="Compute metrics from existing proxy_calls")
    p_proxy_metrics.add_argument("--recent", action="store_true", help="Show recent sessions instead of comparison")
    p_proxy_metrics.add_argument("--limit", "-n", type=int, default=20, help="Number of recent sessions (default: 20)")
    p_proxy_metrics.set_defaults(func=cmd_proxy_metrics)
    p_proxy.set_defaults(func=lambda args: p_proxy.print_help())

    # hook-handle (hidden — called by the shell script)
    p_hook_handle = subparsers.add_parser("hook-handle", help=argparse.SUPPRESS)
    p_hook_handle.set_defaults(func=cmd_hook_handle)

    # mcp
    p_mcp = subparsers.add_parser("mcp", help="Start Engram MCP server (stdio transport)")
    p_mcp.set_defaults(func=cmd_mcp)

    # trail
    p_trail = subparsers.add_parser("trail", help="Show artifact trail for a Claude Code session")
    p_trail.add_argument("session_id", help="Session ID (or prefix) to show trail for")
    p_trail.set_defaults(func=cmd_trail)

    # mcp install (standalone MCP wiring)
    p_mcp_install = subparsers.add_parser("mcp-install", help="Register engram MCP server with Claude Code")
    p_mcp_install.add_argument("--global", dest="global_install", action="store_true", default=True,
                                help="Install to ~/.claude/settings.json (default)")
    p_mcp_install.add_argument("--project", "-p", dest="project_dir",
                                help="Install to project .mcp.json instead")
    p_mcp_install.set_defaults(func=cmd_mcp_install)

    # graph-load
    p_graph_load = subparsers.add_parser("graph-load", help="Load data into Memgraph knowledge graph")
    p_graph_load.add_argument("--bolt-uri", default="bolt://localhost:7687", help="Memgraph Bolt URI (default: bolt://localhost:7687)")
    p_graph_load.add_argument("--db-path", default=None, help="SQLite DB path (default: ~/.config/engram/sessions.db)")
    p_graph_load.add_argument("--project", "-p", help="Filter to a specific project")
    p_graph_load.set_defaults(func=cmd_graph_load)

    # graph-algo
    p_graph_algo = subparsers.add_parser("graph-algo", help="Run graph algorithms (PageRank, community detection)")
    p_graph_algo.add_argument("--bolt-uri", default="bolt://localhost:7687", help="Memgraph Bolt URI (default: bolt://localhost:7687)")
    p_graph_algo.add_argument("--algorithm", "-a", choices=["pagerank", "community", "shortest-path", "all"], default="all", help="Algorithm to run (default: all)")
    p_graph_algo.set_defaults(func=cmd_graph_algo)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
