from __future__ import annotations

from typing import Literal

import flask


def classify_graphql_operation(query: str) -> Literal["query", "mutation"]:
    for line in query.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("mutation"):
            return "mutation"
        return "query"
    return "query"


def increment_request_graphql(kind: Literal["query", "mutation"]) -> None:
    """Increment GraphQL counters on ``flask.g`` for the current request only."""
    if not flask.has_request_context():
        return
    if kind == "mutation":
        flask.g.graphql_mutations = getattr(flask.g, "graphql_mutations", 0) + 1
    else:
        flask.g.graphql_queries = getattr(flask.g, "graphql_queries", 0) + 1
