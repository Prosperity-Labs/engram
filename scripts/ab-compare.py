#!/usr/bin/env python3
"""Compare two engram sessions side-by-side for A/B testing."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engram.recall.session_db import SessionDB
from engram.stats import compute_session_stats


def compare(session_a: str, session_b: str, label_a: str = "Control", label_b: str = "Treatment"):
    db = SessionDB()

    stats_a = compute_session_stats(db, session_a)
    stats_b = compute_session_stats(db, session_b)

    if stats_a["messages"] == 0:
        print(f"Session {session_a} not found or not indexed yet.")
        print("Run: engram install")
        return
    if stats_b["messages"] == 0:
        print(f"Session {session_b} not found or not indexed yet.")
        print("Run: engram install")
        return

    def fmt(val):
        if isinstance(val, float):
            return f"{val:.1%}" if val < 1 else f"{val:.0f}"
        return str(val)

    print(f"\n{'Metric':<25} {label_a:<20} {label_b:<20} {'Delta':<15}")
    print("-" * 80)

    rows = [
        ("Messages", "messages"),
        ("Tool calls", "tool_calls"),
        ("Tokens in", "tokens_in"),
        ("Tokens out", "tokens_out"),
        ("Exploration %", "exploration_ratio"),
        ("Mutation %", "mutation_ratio"),
        ("Execution %", "execution_ratio"),
        ("Error rate", "error_rate"),
    ]

    for label, key in rows:
        a = stats_a.get(key, 0) or 0
        b = stats_b.get(key, 0) or 0

        if isinstance(a, float):
            delta = b - a
            delta_str = f"{delta:+.1%}"
            a_str = f"{a:.0%}"
            b_str = f"{b:.0%}"
        else:
            a, b = int(a), int(b)
            if a > 0:
                pct = ((b - a) / a) * 100
                delta_str = f"{b - a:+d} ({pct:+.0f}%)"
            else:
                delta_str = f"{b - a:+d}"
            a_str = f"{a:,}"
            b_str = f"{b:,}"

        print(f"{label:<25} {a_str:<20} {b_str:<20} {delta_str:<15}")

    # Tool breakdown
    print(f"\n{'Top tools':<25} {label_a:<20} {label_b:<20}")
    print("-" * 65)

    tools_a = {name: count for name, count in (stats_a.get("top_tools") or [])}
    tools_b = {name: count for name, count in (stats_b.get("top_tools") or [])}
    all_tools = sorted(set(tools_a) | set(tools_b), key=lambda t: -(tools_a.get(t, 0) + tools_b.get(t, 0)))

    for tool in all_tools[:10]:
        ca = tools_a.get(tool, 0)
        cb = tools_b.get(tool, 0)
        print(f"  {tool:<23} {ca:<20} {cb:<20}")

    # Verdict
    print("\n" + "=" * 80)
    msgs_a, msgs_b = int(stats_a["messages"] or 0), int(stats_b["messages"] or 0)
    reads_a = tools_a.get("Read", 0)
    reads_b = tools_b.get("Read", 0)

    if msgs_b < msgs_a:
        print(f"  {label_b} used {msgs_a - msgs_b} fewer messages ({(msgs_a - msgs_b)/msgs_a:.0%} reduction)")
    elif msgs_b > msgs_a:
        print(f"  {label_a} used {msgs_b - msgs_a} fewer messages")
    else:
        print(f"  Same message count")

    if reads_b < reads_a:
        print(f"  {label_b} did {reads_a - reads_b} fewer file reads")
    elif reads_b > reads_a:
        print(f"  {label_a} did {reads_b - reads_a} fewer file reads")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare two A/B test sessions")
    parser.add_argument("session_a", help="Control session ID (prefix ok)")
    parser.add_argument("session_b", help="Treatment session ID (prefix ok)")
    parser.add_argument("--label-a", default="Control", help="Label for session A")
    parser.add_argument("--label-b", default="Treatment", help="Label for session B")
    args = parser.parse_args()

    # Support prefix matching
    db = SessionDB()
    with db._connect() as conn:
        for attr in ["session_a", "session_b"]:
            val = getattr(args, attr)
            if len(val) < 36:
                row = conn.execute(
                    "SELECT session_id FROM sessions WHERE session_id LIKE ? ORDER BY updated_at DESC LIMIT 1",
                    (val + "%",),
                ).fetchone()
                if row:
                    setattr(args, attr, row["session_id"])

    compare(args.session_a, args.session_b, args.label_a, args.label_b)
