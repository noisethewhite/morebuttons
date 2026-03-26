from __future__ import annotations

import threading
from typing import Literal

_lock = threading.Lock()
_query_total = 0
_mutation_total = 0


def classify_graphql_operation(query: str) -> Literal["query", "mutation"]:
    for line in query.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("mutation"):
            return "mutation"
        return "query"
    return "query"


def record_graphql(kind: Literal["query", "mutation"]) -> None:
    global _query_total, _mutation_total
    with _lock:
        if kind == "mutation":
            _mutation_total += 1
        else:
            _query_total += 1


def get_totals() -> tuple[int, int]:
    with _lock:
        return _query_total, _mutation_total
