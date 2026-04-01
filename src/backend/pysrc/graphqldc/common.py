from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass


N = TypeVar("N")


@dataclass(config=ConfigDict(extra="ignore"))
class PageInfoDC(object):
    hasNextPage: bool | None = None
    endCursor: str | None = None


@dataclass(config=ConfigDict(extra="ignore"))
class EdgeDC(Generic[N]):
    """Relay-style edge: ``node`` plus optional ``cursor``."""

    node: N
    cursor: str | None = None


@dataclass(config=ConfigDict(extra="ignore"))
class ConnectionDC(Generic[N]):
    """Relay-style connection: ``edges`` + ``pageInfo``."""

    edges: list[EdgeDC[N]]
    pageInfo: PageInfoDC
