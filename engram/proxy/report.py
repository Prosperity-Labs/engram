"""Measurement comparison report: baseline vs. enriched proxy calls."""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path.home() / ".config" / "engram" / "sessions.db"


def generate_report(db_path: str | None = None, project: str | None = None) -> str:
    """Generate a comparison report of baseline vs. enriched proxy calls.

    Groups proxy_calls by enrichment_variant (NULL = baseline) and shows
    count, avg tokens, avg cost, and deltas.
    """
    path = db_path or str(DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    where = ""
    params: list = []
    if project:
        where = "WHERE project = ?"
        params.append(project)

    try:
        rows = conn.execute(
            f"""
            SELECT COALESCE(enrichment_variant, 'baseline') AS variant,
                   COUNT(*) AS calls,
                   CAST(AVG(input_tokens) AS INTEGER) AS avg_in,
                   CAST(AVG(output_tokens) AS INTEGER) AS avg_out,
                   ROUND(AVG(cost_estimate_usd), 6) AS avg_cost,
                   ROUND(SUM(cost_estimate_usd), 4) AS total_cost
            FROM proxy_calls
            {where}
            GROUP BY COALESCE(enrichment_variant, 'baseline')
            ORDER BY variant
            """,
            params,
        ).fetchall()
    except sqlite3.OperationalError:
        return "No proxy data yet. Start the proxy first: engram proxy start"
    finally:
        conn.close()

    if not rows:
        return "No proxy calls recorded yet."

    groups = {row["variant"]: dict(row) for row in rows}

    lines = ["Engram Proxy — Enrichment Report"]
    if project:
        lines.append(f"Project: {project}")
    lines.append("=" * 60)
    lines.append("")

    header = f"{'Variant':<12} {'Calls':>7} {'Avg In':>9} {'Avg Out':>9} {'Avg Cost':>10} {'Total Cost':>11}"
    lines.append(header)
    lines.append("-" * len(header))

    for variant, g in sorted(groups.items()):
        lines.append(
            f"{variant:<12} {g['calls']:>7,} {g['avg_in']:>9,} {g['avg_out']:>9,} "
            f"${g['avg_cost']:>9.6f} ${g['total_cost']:>10.4f}"
        )

    # Show delta if both baseline and enriched exist
    baseline = groups.get("baseline")
    enriched = {k: v for k, v in groups.items() if k != "baseline"}
    if baseline and enriched:
        lines.append("")
        lines.append("Delta (enriched vs. baseline):")
        for variant, e in sorted(enriched.items()):
            b = baseline
            d_in = e["avg_in"] - b["avg_in"]
            d_out = e["avg_out"] - b["avg_out"]
            d_cost = e["avg_cost"] - b["avg_cost"]
            sign = lambda v: f"+{v}" if v >= 0 else str(v)
            lines.append(
                f"  {variant}: avg_in {sign(d_in)}, avg_out {sign(d_out)}, "
                f"avg_cost {sign(round(d_cost, 6))}"
            )

    return "\n".join(lines)
