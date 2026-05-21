from __future__ import annotations

import csv
import io
import logging
import uuid
from dataclasses import dataclass, field
from typing import Literal

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass as pydantic_dataclass

from .fileloader import FileLoader
from .graphql import GraphQL
from .graphqldc.common import Jsonable
from .graphqldc.orders import OrderNode, OrdersByTrackingData
from .order_lookup import _node_to_result

_log = logging.getLogger(__name__)
_PC = ConfigDict(extra="ignore")


@pydantic_dataclass(config=_PC)
class CsvStepPending(Jsonable):
    completed: int
    total: int
    done: Literal[False] = False


@pydantic_dataclass(config=_PC)
class CsvStepDone(Jsonable):
    completed: int
    total: int
    orderCount: int
    csvData: str
    done: Literal[True] = True


CsvStepResult = CsvStepPending | CsvStepDone


def _build_csv(nodes: list[OrderNode], packaging_weight_g: int) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Order number", "Status", "Customer", "Address",
        "Gross weight (g)", "Delivery cost", "Delivery method", "Total",
        "Tracking numbers",
    ])
    for node in nodes:
        result = _node_to_result(node)
        tracking_numbers = [
            ti.number
            for f in node.fulfillments
            for ti in f.trackingInfo
            if ti.number
        ]
        addr = result.address
        address_str = ""
        if addr:
            address_str = ", ".join(filter(None, [
                addr.address1, addr.address2, addr.city,
                addr.province, addr.zip,
                addr.country if addr.country else addr.countryCode,
            ]))
        weight: int | None = None
        if result.weightGrams is not None or packaging_weight_g:
            weight = (result.weightGrams or 0) + packaging_weight_g
        writer.writerow([
            result.orderNumber,
            result.status.replace("_", " "),
            result.customerName,
            address_str,
            weight if weight is not None else "",
            result.deliveryCost or "",
            result.deliveryTitle or "",
            result.orderTotal or "",
            ", ".join(tracking_numbers),
        ])
    return buf.getvalue()


@dataclass
class OrderLookupCsvJob:
    id: str
    shop_domain: str
    token: str
    date_from: str | None
    date_to: str | None
    packaging_weight_g: int
    nodes: list[OrderNode] = field(default_factory=list)
    after: str | None = None
    all_done: bool = False
    completed_pages: int = 0
    _query: str = field(init=False)

    def __post_init__(self) -> None:
        self._query = FileLoader.load("order_by_tracking.gql")

    def _shopify_query(self) -> str:
        parts: list[str] = ["fulfillment_status:fulfilled"]
        if self.date_from:
            parts.append(f"created_at:>={self.date_from}")
        if self.date_to:
            parts.append(f"created_at:<={self.date_to}")
        return " ".join(parts)

    def step(self) -> CsvStepResult:
        if self.all_done:
            return self._finish()

        _log.info(
            "CsvJob page=%d after=%r query=%r",
            self.completed_pages,
            self.after,
            self._shopify_query(),
        )
        parsed = GraphQL.send(
            self.shop_domain,
            self.token,
            self._query,
            {"first": 250, "after": self.after, "query": self._shopify_query()},
            expected_type=OrdersByTrackingData,
        )

        if parsed is None:
            _log.warning("CsvJob page=%d parsed=None, finishing", self.completed_pages)
            self.all_done = True
            return self._finish()

        conn = parsed.orders
        _log.info(
            "CsvJob page=%d edges=%d hasNextPage=%r endCursor=%r",
            self.completed_pages,
            len(conn.edges),
            conn.pageInfo.hasNextPage,
            conn.pageInfo.endCursor,
        )
        for edge in conn.edges:
            self.nodes.append(edge.node)

        self.completed_pages += 1
        nxt = conn.pageInfo.next_page_cursor()

        if nxt is None:
            self.all_done = True
            return self._finish()

        self.after = nxt
        return self._pending()

    def _pending(self) -> CsvStepPending:
        return CsvStepPending(
            completed=self.completed_pages,
            total=self.completed_pages + 1,
        )

    def _finish(self) -> CsvStepDone:
        return CsvStepDone(
            completed=self.completed_pages,
            total=self.completed_pages,
            orderCount=len(self.nodes),
            csvData=_build_csv(self.nodes, self.packaging_weight_g),
        )


_CSV_JOBS: dict[str, OrderLookupCsvJob] = {}


def create_order_lookup_csv_job(
    shop_domain: str,
    token: str,
    date_from: str | None,
    date_to: str | None,
    packaging_weight_g: int,
) -> str:
    jid = uuid.uuid4().hex
    _CSV_JOBS[jid] = OrderLookupCsvJob(
        id=jid,
        shop_domain=shop_domain,
        token=token,
        date_from=date_from,
        date_to=date_to,
        packaging_weight_g=packaging_weight_g,
    )
    return jid


def take_order_lookup_csv_job(job_id: str) -> OrderLookupCsvJob | None:
    return _CSV_JOBS.get(job_id)


def delete_order_lookup_csv_job(job_id: str) -> None:
    _CSV_JOBS.pop(job_id, None)
