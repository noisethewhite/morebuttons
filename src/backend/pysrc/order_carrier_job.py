from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from .fileloader import FileLoader
from .graphql import GraphQL
from .graphqldc.orders import (
    OrderCarrierCatalogData,
    OrderCarrierStepDone,
    OrderCarrierStepPending,
    OrderCarrierStepResult,
)

_log = logging.getLogger(__name__)


@dataclass
class OrderCarrierJob:
    """Stepped job: paginate fulfilled Shopify orders and collect unique carrier names."""

    id: str
    shop_domain: str
    token: str
    max_orders: int
    date_from: str | None
    date_to: str | None
    carriers: set[str] = field(default_factory=set)
    orders_scanned: int = 0
    after: str | None = None
    all_done: bool = False
    completed_steps: int = 0
    _query: str = field(init=False)

    def __post_init__(self) -> None:
        self._query = FileLoader.load("order_carrier_catalog_page.gql")

    def _shopify_query(self) -> str:
        parts: list[str] = ["fulfillment_status:fulfilled"]
        if self.date_from:
            parts.append(f"created_at:>={self.date_from}")
        if self.date_to:
            parts.append(f"created_at:<={self.date_to}")
        return " ".join(parts)

    def step(self) -> OrderCarrierStepResult:
        if self.all_done:
            return self._finish()

        self.completed_steps += 1
        batch_size = min(250, self.max_orders - self.orders_scanned)
        if batch_size <= 0:
            self.all_done = True
            return self._finish()

        _log.info(
            "CarrierJob step=%d after=%r batch=%d scanned=%d",
            self.completed_steps,
            self.after,
            batch_size,
            self.orders_scanned,
        )
        parsed = GraphQL.send(
            self.shop_domain,
            self.token,
            self._query,
            {
                "first": batch_size,
                "after": self.after,
                "query": self._shopify_query(),
            },
            expected_type=OrderCarrierCatalogData,
        )

        if parsed is None:
            _log.warning("CarrierJob step=%d parsed=None, finishing", self.completed_steps)
            self.all_done = True
            return self._finish()

        conn = parsed.orders
        _log.info(
            "CarrierJob step=%d edges=%d hasNextPage=%r endCursor=%r",
            self.completed_steps,
            len(conn.edges),
            conn.pageInfo.hasNextPage,
            conn.pageInfo.endCursor,
        )
        for edge in conn.edges:
            for fulfillment in edge.node.fulfillments:
                for ti in fulfillment.trackingInfo:
                    if ti.company:
                        self.carriers.add(ti.company)

        self.orders_scanned += len(conn.edges)

        nxt = conn.pageInfo.next_page_cursor()
        if nxt is None or self.orders_scanned >= self.max_orders:
            self.all_done = True
            return self._finish()

        self.after = nxt
        return self._pending()

    def _pending(self) -> OrderCarrierStepPending:
        return OrderCarrierStepPending(
            completed=self.completed_steps,
            remaining=1,
            total=self.completed_steps + 1,
        )

    def _finish(self) -> OrderCarrierStepDone:
        return OrderCarrierStepDone(
            carriers=sorted(self.carriers),
            completed=self.completed_steps,
            total=self.completed_steps,
        )


_JOBS: dict[str, OrderCarrierJob] = {}


def create_order_carrier_job(
    shop_domain: str,
    token: str,
    max_orders: int,
    date_from: str | None,
    date_to: str | None,
) -> str:
    jid = uuid.uuid4().hex
    _JOBS[jid] = OrderCarrierJob(
        id=jid,
        shop_domain=shop_domain,
        token=token,
        max_orders=max_orders,
        date_from=date_from,
        date_to=date_to,
    )
    return jid


def take_order_carrier_job(job_id: str) -> OrderCarrierJob | None:
    return _JOBS.get(job_id)


def delete_order_carrier_job(job_id: str) -> None:
    _ = _JOBS.pop(job_id, None)
