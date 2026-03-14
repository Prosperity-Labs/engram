"""Engram knowledge graph module — Memgraph/Neo4j integration."""

from __future__ import annotations

from .loader import GraphLoader


def get_driver(
    bolt_uri: str = "bolt://localhost:7687",
    auth: tuple[str, str] | None = None,
):
    """Create a Neo4j/Memgraph Bolt driver.

    Memgraph uses no auth by default; pass auth=("user", "pass") if configured.
    """
    from neo4j import GraphDatabase

    if auth is None:
        return GraphDatabase.driver(bolt_uri)
    return GraphDatabase.driver(bolt_uri, auth=auth)


__all__ = ["GraphLoader", "get_driver"]
