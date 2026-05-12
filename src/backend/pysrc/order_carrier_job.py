from __future__ import annotations

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


@dataclass
class OrderCarrierJob:
    """Stepped job: paginate Shopify orders and collect unique carrier names."""

    id: str
    shop_domain: str
    token: str
    max_orders: int
    date_from: str | None
    date_to: str | None
    carriers: set[str] = field(default_factory=set)
    orders_scanned: int = 0
    after: str | None = None
    exhausted: bool = False
    completed_steps: int = 0
    _query: str = field(init=False)

    def __post_init__(self) -> None:
        self._query = FileLoader.load("order_carrier_catalog_page.gql")

    def _build_shopify_query(self) -> str | None:
        parts: list[str] = []
        if self.date_from:
            parts.append(f"created_at:>={self.date_from}")
        if self.date_to:
            parts.append(f"created_at:<={self.date_to}")
        return " ".join(parts) if parts else None

    def step(self) -> OrderCarrierStepResult:
        if self.exhausted:
            return self._finish()

        self.completed_steps += 1
        batch_size = min(250, self.max_orders - self.orders_scanned)
        if batch_size <= 0:
            self.exhausted = True
            return self._finish()

        parsed = GraphQL.send(
            self.shop_domain,
            self.token,
            self._query,
            {
                "first": batch_size,
                "after": self.after,
                "query": self._build_shopify_query(),
            },
            expected_type=OrderCarrierCatalogData,
        )

        if parsed is None:
            self.exhausted = True
            return self._finish()

        conn = parsed.orders
        for edge in conn.edges:
            for fulfillment in edge.node.fulfillments:
                for ti in fulfillment.trackingInfo:
                    if ti.company:
                        self.carriers.add(ti.company)

        self.orders_scanned += min(len(conn.edges), batch_size)

        nxt = conn.pageInfo.next_page_cursor()
        if nxt is None or self.orders_scanned >= self.max_orders:
            self.exhausted = True
            self.after = None
        else:
            self.after = nxt

        if self.exhausted:
            return self._finish()

        pages_remaining = max(0, (self.max_orders - self.orders_scanned + 249) // 250)
        return OrderCarrierStepPending(
            completed=self.completed_steps,
            remaining=pages_remaining,
            total=self.completed_steps + pages_remaining,
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
