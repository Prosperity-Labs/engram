"""Knowledge base monitor — shows live stats and indexes active sessions."""

from __future__ import annotations

import sqlite3
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path


# Unicode sparkline blocks (8 levels)
_SPARK = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587"


def _spark(values: list[int]) -> str:
    """Render a list of ints as a unicode sparkline."""
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if hi == lo:
        return _SPARK[4] * len(values)  # flat line at mid-height
    spread = hi - lo
    return "".join(_SPARK[min(len(_SPARK) - 1, int((v - lo) / spread * (len(_SPARK) - 1)))] for v in values)


def snapshot() -> dict:
    """Collect current stats from the SQLite session store."""
    from .recall.session_db import SessionDB

    db = SessionDB()
    stats = db.stats()
    stats["timestamp"] = datetime.now().isoformat(timespec="seconds")

    # Role and tool breakdown
    try:
        conn = sqlite3.connect(str(db.db_path), timeout=5)
        conn.row_factory = sqlite3.Row

        roles = {}
        for row in conn.execute("SELECT role, COUNT(*) as c FROM messages GROUP BY role"):
            roles[row["role"]] = row["c"]
        stats["roles"] = roles

        tools = []
        for row in conn.execute(
            "SELECT tool_name, COUNT(*) as c FROM messages "
            "WHERE tool_name IS NOT NULL GROUP BY tool_name ORDER BY c DESC LIMIT 8"
        ):
            tools.append((row["tool_name"], row["c"]))
        stats["top_tools"] = tools

        sessions = []
        for row in conn.execute(
            "SELECT s.session_id, s.project, s.message_count, "
            "SUM(CASE WHEN m.tool_name IS NOT NULL THEN 1 ELSE 0 END) as tool_calls "
            "FROM sessions s LEFT JOIN messages m ON m.session_id = s.session_id "
            "GROUP BY s.session_id ORDER BY s.message_count DESC"
        ):
            sessions.append({
                "id": row["session_id"][:12],
                "project": row["project"] or "?",
                "messages": row["message_count"],
                "tools": row["tool_calls"],
            })
        stats["sessions"] = sessions

        conn.close()
    except Exception:
        stats["roles"] = {}
        stats["top_tools"] = []
        stats["sessions"] = []

    return stats


def _format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _format_tokens(n: int) -> str:
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}K"
    return f"{n / 1_000_000:.1f}M"


def _bar(value: int, max_val: int, width: int = 20) -> str:
    """Render a proportional bar using unicode blocks."""
    if max_val == 0:
        return ""
    filled = int(value / max_val * width)
    return "\u2588" * filled + "\u2591" * (width - filled)


def render(
    snap: dict,
    prev: dict | None = None,
    live_stats: dict | None = None,
    history: list[int] | None = None,
) -> str:
    """Render a snapshot as a human-readable display."""
    lines = []

    # Header stats
    msg_count = snap["total_messages"]
    spark = f"  [{_spark(history)}]" if history and len(history) > 1 else ""
    delta_str = ""
    if prev and msg_count != prev["total_messages"]:
        d = msg_count - prev["total_messages"]
        delta_str = f"  (+{d})"

    lines.append(f"  Messages:   {msg_count}{delta_str}{spark}")
    lines.append(f"  Sessions:   {snap['total_sessions']}")
    lines.append(f"  Tokens:     {_format_tokens(snap['total_tokens_in'])} in / {_format_tokens(snap['total_tokens_out'])} out")
    lines.append(f"  DB size:    {_format_bytes(snap['db_size_bytes'])}")

    # Role breakdown
    roles = snap.get("roles", {})
    if roles:
        lines.append("")
        lines.append("  Role Breakdown")
        lines.append("  " + "-" * 40)
        total = sum(roles.values()) or 1
        for role in ["user", "assistant", "summary"]:
            c = roles.get(role, 0)
            pct = c / total * 100
            bar = _bar(c, total, 16)
            lines.append(f"    {role:12s} {c:>5}  {bar} {pct:.0f}%")

    # Top tools
    tools = snap.get("top_tools", [])
    if tools:
        lines.append("")
        lines.append("  Tool Usage")
        lines.append("  " + "-" * 40)
        max_t = tools[0][1] if tools else 1
        for name, count in tools[:6]:
            short = name.replace("mcp__postgres__", "pg:").replace("mcp__", "")
            bar = _bar(count, max_t, 12)
            lines.append(f"    {short:22s} {count:>4}  {bar}")

    # Active sessions
    sessions = snap.get("sessions", [])
    if sessions:
        lines.append("")
        lines.append("  Active Sessions")
        lines.append("  " + "-" * 40)
        max_m = sessions[0]["messages"] if sessions else 1
        for s in sessions:
            bar = _bar(s["messages"], max_m, 10)
            lines.append(f"    {s['id']}  {s['project']:12s} {s['messages']:>5} msgs {bar}")

    # Live indexer stats
    if live_stats:
        lines.append("")
        lines.append("  Live Indexer")
        lines.append("  " + "-" * 40)
        lines.append(f"    Polls:     {live_stats.get('polls', 0)}")
        lines.append(f"    Indexed:   {live_stats.get('total_new_messages', 0)} new messages")
        lines.append(f"    Tracking:  {live_stats.get('sessions_seen', 0)} sessions")

    return "\n".join(lines)


def watch(interval: int = 10, live_index: bool = True) -> None:
    """Poll loop: optionally index active sessions, then display stats."""
    indexer = None
    if live_index:
        from .recall.live_indexer import LiveIndexer
        indexer = LiveIndexer()

    prev = None
    history: deque[int] = deque(maxlen=30)  # last 30 polls

    try:
        while True:
            poll_result = None
            if indexer:
                poll_result = indexer.poll()

            snap = snapshot()
            history.append(snap["total_messages"])
            live_stats = indexer.cumulative_stats() if indexer else None

            # Clear screen and render
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.write(f"  Engram Knowledge Base Monitor  [{snap['timestamp']}]\n")
            sys.stdout.write("  " + "=" * 48 + "\n\n")
            sys.stdout.write(render(snap, prev, live_stats, list(history)))
            sys.stdout.write("\n\n")

            if poll_result and poll_result.get("new_messages", 0) > 0:
                sys.stdout.write(
                    f"  >> +{poll_result['new_messages']} messages "
                    f"from {poll_result['sessions_polled']} session(s) this cycle\n"
                )

            sys.stdout.write(f"\n  Refreshing every {interval}s. Ctrl+C to stop.\n")
            sys.stdout.flush()

            prev = snap
            time.sleep(interval)

    except KeyboardInterrupt:
        sys.stdout.write("\nStopped.\n")
