"""Graph algorithms using Memgraph MAGE procedures.

Wraps PageRank, community detection, and shortest path queries.
"""

from __future__ import annotations

from typing import Any

from neo4j import Driver


def run_pagerank(driver: Driver, limit: int = 20) -> list[dict[str, Any]]:
    """Run PageRank on the graph, return top files by centrality."""
    cypher = """
        CALL pagerank.get()
        YIELD node, rank
        WITH node, rank
        WHERE node:File
        RETURN node.path AS path,
               node.name AS name,
               node.project AS project,
               rank
        ORDER BY rank DESC
        LIMIT $limit
    """
    with driver.session() as session:
        result = session.run(cypher, limit=limit)
        return [dict(r) for r in result]


def run_community_detection(driver: Driver, limit: int = 10) -> list[dict[str, Any]]:
    """Detect file communities using label propagation."""
    cypher = """
        CALL community_detection.get()
        YIELD node, community_id
        WITH node, community_id
        WHERE node:File
        RETURN community_id,
               collect(node.path) AS files,
               count(*) AS size
        ORDER BY size DESC
        LIMIT $limit
    """
    with driver.session() as session:
        result = session.run(cypher, limit=limit)
        return [dict(r) for r in result]


def run_shortest_path(
    driver: Driver,
    start_concept: str | None = None,
    end_concept: str | None = None,
) -> list[dict[str, Any]]:
    """Find shortest path between two concepts.

    If concepts not specified, picks the top 2 by frequency.
    """
    if not start_concept or not end_concept:
        # Auto-select top 2 concepts
        cypher_top = """
            MATCH (c:Concept)
            RETURN c.name AS name
            ORDER BY c.frequency DESC
            LIMIT 2
        """
        with driver.session() as session:
            top = [r["name"] for r in session.run(cypher_top)]
        if len(top) < 2:
            return [{"error": "Need at least 2 Concept nodes for shortest path"}]
        start_concept = start_concept or top[0]
        end_concept = end_concept or top[1]

    # Memgraph uses BFS shortest path syntax
    cypher = """
        MATCH p = (c1:Concept {name: $start})-[*BFS ..6]-(c2:Concept {name: $end})
        WITH p,
             [n IN nodes(p) | labels(n)[0] + ': ' +
                COALESCE(n.name, n.path, n.pattern, n.id, 'unknown')] AS path_nodes,
             size(relationships(p)) AS hops
        RETURN path_nodes, hops
        LIMIT 5
    """
    with driver.session() as session:
        result = session.run(cypher, start=start_concept, end=end_concept)
        paths = [dict(r) for r in result]

    if not paths:
        return [{"error": f"No path found between '{start_concept}' and '{end_concept}'"}]
    return paths


def run_algorithms(
    driver: Driver,
    algorithm: str = "all",
) -> dict[str, Any]:
    """Run selected or all graph algorithms.

    Args:
        algorithm: "pagerank", "community", "shortest-path", or "all"
    """
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}

    algos = {
        "pagerank": lambda: run_pagerank(driver),
        "community": lambda: run_community_detection(driver),
        "shortest-path": lambda: run_shortest_path(driver),
    }

    to_run = algos if algorithm == "all" else {algorithm: algos[algorithm]}

    for name, fn in to_run.items():
        try:
            results[name] = fn()
        except Exception as e:
            errors[name] = str(e)

    if errors:
        results["errors"] = errors
    return results
