from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import ConfigDict, TypeAdapter
from pydantic.dataclasses import dataclass
from typing import cast
from ..web_types import Json


_CONFIG = ConfigDict(extra="ignore")
_T = TypeVar("_T")


@dataclass(config=_CONFIG)
class PageInfo(object):
    hasNextPage: bool | None = None
    endCursor: str | None = None


@dataclass(config=_CONFIG)
class Edge(Generic[_T]):
    node: _T
    cursor: str | None = None


@dataclass(config=_CONFIG)
class Connection(Generic[_T]):
    edges: list[Edge[_T]]
    pageInfo: PageInfo


@dataclass(config=_CONFIG)
class Jsonable:
    def to_json(self) -> Json.Object:
        return cast(Json.Object, TypeAdapter(type(self)).dump_python(self, exclude_none=True, mode="json"))
