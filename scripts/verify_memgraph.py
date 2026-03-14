#!/usr/bin/env python3
"""Verify Memgraph connection and MAGE availability."""

from __future__ import annotations

import sys


def main() -> None:
    bolt_uri = sys.argv[1] if len(sys.argv) > 1 else "bolt://localhost:7687"

    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("FAIL: neo4j driver not installed. Run: pip install -e '.[graph]'")
        sys.exit(1)

    print(f"Connecting to {bolt_uri}...")
    driver = GraphDatabase.driver(bolt_uri)

    try:
        driver.verify_connectivity()
        print("OK: Bolt connection established")
    except Exception as e:
        print(f"FAIL: Cannot connect — {e}")
        print("Start Memgraph: docker run -d --name engram-memgraph -p 7687:7687 memgraph/memgraph-mage:latest")
        sys.exit(1)

    with driver.session() as session:
        # Check MAGE procedures
        mage_procs = ["pagerank.get", "community_detection.get"]
        for proc in mage_procs:
            try:
                # Just check if the procedure exists by calling with empty graph
                result = session.run(f"CALL mg.procedures() YIELD name WHERE name = '{proc}' RETURN name")
                found = [r["name"] for r in result]
                if found:
                    print(f"OK: MAGE procedure '{proc}' available")
                else:
                    print(f"WARN: MAGE procedure '{proc}' not found — use memgraph/memgraph-mage image")
            except Exception as e:
                print(f"WARN: Could not check '{proc}' — {e}")

        # Node/edge counts
        try:
            node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            edge_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            print(f"\nGraph: {node_count} nodes, {edge_count} edges")

            if node_count > 0:
                labels = session.run(
                    "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS cnt ORDER BY cnt DESC"
                )
                for r in labels:
                    print(f"  {r['label']}: {r['cnt']}")
        except Exception as e:
            print(f"WARN: Could not query counts — {e}")

    driver.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
