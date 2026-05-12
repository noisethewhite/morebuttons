# Order Lookup Tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third "Order lookup" tab that lets users search for an order by tracking number, optionally pre-filtered by delivery carrier, where the carrier list is populated by a stepped job that scans the last N orders within a date range.

**Architecture:** Two new Shopify Admin GraphQL queries; a stepped job (same pattern as `shipping_catalog_job.py`) to paginate orders and collect carrier names; a single-request lookup by tracking number with backend carrier filtering; three new Flask routes; one new React panel component wired into the existing two-tab layout.

**Tech Stack:** Python 3 / Flask / Pydantic v2 (`pydantic.dataclasses`) / pytest — backend. React 18 / TypeScript / esbuild — frontend.

---

## File Map

| Status | Path | Responsibility |
|---|---|---|
| Create | `src/backend/graphql/order_carrier_catalog_page.gql` | Paginated orders → carrier names only |
| Create | `src/backend/graphql/order_by_tracking.gql` | Full order detail lookup by tracking number |
| Create | `src/backend/pysrc/graphqldc/orders.py` | All order pydantic dataclasses + API response shapes |
| Create | `src/backend/pysrc/order_carrier_job.py` | Stepped job: paginate orders, collect carrier names |
| Create | `src/backend/pysrc/order_lookup.py` | `lookup_order_by_tracking()` |
| Create | `tests/__init__.py` | Test package root |
| Create | `tests/backend/__init__.py` | Backend test sub-package |
| Create | `tests/backend/test_graphqldc_orders.py` | Dataclass + serialisation tests |
| Create | `tests/backend/test_order_carrier_job.py` | Job step logic tests |
| Create | `tests/backend/test_order_lookup.py` | Lookup function tests |
| Create | `tests/backend/test_order_routes.py` | Flask route tests |
| Modify | `src/backend/pysrc/routes.py` | Add 3 new route constants |
| Modify | `src/backend/main.py` | Add 3 new route handlers + imports |
| Create | `src/frontend/styles/order-lookup.css` | BEM styles, prefix `order-lookup__` |
| Modify | `src/frontend/templates/index.html` | Link new CSS |
| Modify | `esbuild.mjs` | Copy new CSS to `dist/` |
| Create | `src/frontend/tsxsrc/OrderLookupPanel.tsx` | New tab panel |
| Modify | `src/frontend/tsxsrc/app.tsx` | Add "Order lookup" tab button + panel |

---

### Task 1: GraphQL query files

**Files:**
- Create: `src/backend/graphql/order_carrier_catalog_page.gql`
- Create: `src/backend/graphql/order_by_tracking.gql`

- [ ] **Step 1: Create `order_carrier_catalog_page.gql`**

```graphql
query OrderCarrierPage($first: Int!, $after: String, $query: String) {
  orders(first: $first, after: $after, query: $query, sortKey: CREATED_AT, reverse: true) {
    edges {
      node {
        fulfillments {
          trackingInfo {
            company
          }
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
```

- [ ] **Step 2: Create `order_by_tracking.gql`**

```graphql
query OrderByTracking($query: String!) {
  orders(first: 10, query: $query) {
    edges {
      node {
        id
        name
        displayFulfillmentStatus
        customer {
          firstName
          lastName
        }
        shippingAddress {
          address1
          address2
          city
          province
          country
          zip
          countryCodeV2
        }
        totalWeight
        shippingLine {
          title
          originalPriceSet {
            shopMoney {
              amount
              currencyCode
            }
          }
        }
        currentTotalPriceSet {
          shopMoney {
            amount
            currencyCode
          }
        }
        fulfillments {
          trackingInfo {
            number
            company
            url
          }
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add src/backend/graphql/order_carrier_catalog_page.gql src/backend/graphql/order_by_tracking.gql
git commit -m "feat: add order carrier catalog and tracking lookup GQL queries"
```

---

### Task 2: Dataclasses — `graphqldc/orders.py`

**Files:**
- Create: `src/backend/pysrc/graphqldc/orders.py`
- Create: `tests/__init__.py`
- Create: `tests/backend/__init__.py`
- Create: `tests/backend/test_graphqldc_orders.py`

All dataclasses use `pydantic.dataclasses.dataclass` with `ConfigDict(extra="ignore")` — identical to the existing `graphqldc/shipping.py` pattern.

- [ ] **Step 1: Install pytest**

```bash
pip install pytest
```

- [ ] **Step 2: Create empty test package files**

```bash
touch tests/__init__.py tests/backend/__init__.py
```

- [ ] **Step 3: Write failing tests**

Create `tests/backend/test_graphqldc_orders.py`:

```python
import pytest
from backend.pysrc.graphqldc.orders import (
    MoneyV2,
    MoneyBag,
    FulfillmentTrackingInfo,
    FulfillmentNode,
    OrderCarrierNode,
    OrderCarrierCatalogData,
    MailingAddress,
    CustomerNode,
    ShippingLine,
    OrderNode,
    OrdersByTrackingData,
    OrderResultAddress,
    OrderResult,
    OrderCarrierStepPending,
    OrderCarrierStepDone,
)
from backend.pysrc.graphqldc.common import Connection, Edge, PageInfo
from backend.pysrc.utils import Utils


# ── MoneyV2 / MoneyBag ──────────────────────────────────────────────────────

def test_money_v2_fields():
    m = MoneyV2(amount="12.50", currencyCode="EUR")
    assert m.amount == "12.50"
    assert m.currencyCode == "EUR"


def test_money_bag_fields():
    shop = MoneyV2(amount="5.00", currencyCode="USD")
    bag = MoneyBag(shopMoney=shop)
    assert bag.shopMoney.amount == "5.00"
    assert bag.presentmentMoney is None


def test_money_bag_extra_fields_ignored():
    shop = MoneyV2(amount="1.00", currencyCode="GBP")
    # presentmentMoney is optional; extra unknown keys are silently dropped
    bag = MoneyBag(shopMoney=shop, presentmentMoney=None)
    assert bag.presentmentMoney is None


# ── FulfillmentTrackingInfo ─────────────────────────────────────────────────

def test_tracking_info_all_none():
    ti = FulfillmentTrackingInfo()
    assert ti.company is None
    assert ti.number is None
    assert ti.url is None


def test_tracking_info_with_values():
    ti = FulfillmentTrackingInfo(company="DHL", number="1Z999AA10123456784", url="https://track.dhl.com")
    assert ti.company == "DHL"


# ── OrderCarrierNode / OrderCarrierCatalogData ──────────────────────────────

def test_order_carrier_catalog_data_parsed_via_dict2dc():
    raw = {
        "orders": {
            "edges": [
                {
                    "node": {
                        "fulfillments": [
                            {"trackingInfo": [{"company": "FedEx", "number": "123"}]}
                        ]
                    }
                }
            ],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        }
    }
    parsed = Utils.dict2dc(raw, OrderCarrierCatalogData)
    assert parsed is not None
    node = parsed.orders.edges[0].node
    assert node.fulfillments[0].trackingInfo[0].company == "FedEx"


# ── OrderNode ───────────────────────────────────────────────────────────────

def _make_order_node_raw() -> dict:
    return {
        "id": "gid://shopify/Order/1",
        "name": "#1001",
        "displayFulfillmentStatus": "FULFILLED",
        "fulfillments": [
            {"trackingInfo": [{"company": "DHL", "number": "ABC", "url": "https://dhl.com"}]}
        ],
        "currentTotalPriceSet": {
            "shopMoney": {"amount": "49.90", "currencyCode": "EUR"}
        },
        "customer": {"firstName": "Jane", "lastName": "Smith"},
        "shippingAddress": {
            "address1": "123 Main St",
            "city": "Berlin",
            "zip": "10115",
            "country": "Germany",
            "countryCodeV2": "DE",
        },
        "totalWeight": 1200,
        "shippingLine": {
            "title": "DHL Express",
            "originalPriceSet": {
                "shopMoney": {"amount": "5.90", "currencyCode": "EUR"}
            },
        },
    }


def test_order_node_parsed_via_dict2dc():
    raw_data = {"orders": {"edges": [{"node": _make_order_node_raw()}], "pageInfo": {"hasNextPage": False}}}
    parsed = Utils.dict2dc(raw_data, OrdersByTrackingData)
    assert parsed is not None
    node = parsed.orders.edges[0].node
    assert node.name == "#1001"
    assert node.displayFulfillmentStatus == "FULFILLED"
    assert node.customer is not None
    assert node.customer.firstName == "Jane"
    assert node.totalWeight == 1200
    assert node.shippingLine is not None
    assert node.shippingLine.title == "DHL Express"
    assert node.currentTotalPriceSet.shopMoney.amount == "49.90"


def test_order_node_guest_checkout():
    raw = _make_order_node_raw()
    raw["customer"] = None
    raw_data = {"orders": {"edges": [{"node": raw}], "pageInfo": {"hasNextPage": False}}}
    parsed = Utils.dict2dc(raw_data, OrdersByTrackingData)
    assert parsed is not None
    assert parsed.orders.edges[0].node.customer is None


# ── OrderResult (Jsonable) ───────────────────────────────────────────────────

def test_order_result_to_json_excludes_none():
    result = OrderResult(
        orderNumber="#1001",
        status="FULFILLED",
        customerName="Jane Smith",
        orderTotal="€49.90",
    )
    j = result.to_json()
    assert j["orderNumber"] == "#1001"
    assert "address" not in j          # None fields excluded
    assert "weightGrams" not in j
    assert "deliveryCost" not in j


def test_order_result_to_json_with_address():
    addr = OrderResultAddress(address1="123 Main St", city="Berlin", zip="10115", countryCode="DE")
    result = OrderResult(
        orderNumber="#1002",
        status="UNFULFILLED",
        customerName="Guest",
        address=addr,
        orderTotal="$10.00",
    )
    j = result.to_json()
    assert j["address"]["city"] == "Berlin"
    assert "address2" not in j["address"]   # None excluded from nested object too


# ── OrderCarrierStepPending / Done (Jsonable) ────────────────────────────────

def test_carrier_step_pending_to_json():
    p = OrderCarrierStepPending(completed=2, remaining=3, total=5)
    j = p.to_json()
    assert j["done"] is False
    assert j["phase"] == "order_carrier"
    assert j["completed"] == 2


def test_carrier_step_done_to_json():
    d = OrderCarrierStepDone(carriers=["DHL", "FedEx"], completed=4, total=4)
    j = d.to_json()
    assert j["done"] is True
    assert j["carriers"] == ["DHL", "FedEx"]
    assert j["remaining"] == 0
```

- [ ] **Step 4: Run tests — expect ImportError (module doesn't exist yet)**

```bash
PYTHONPATH=src pytest tests/backend/test_graphqldc_orders.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.pysrc.graphqldc.orders'`

- [ ] **Step 5: Create `src/backend/pysrc/graphqldc/orders.py`**

```python
from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from .common import Connection, Jsonable

_CONFIG = ConfigDict(extra="ignore")


# ─── Shared money types ────────────────────────────────────────────────────


@dataclass(config=_CONFIG)
class MoneyV2:
    amount: str        # Decimal! in GQL; arrives as decimal string in JSON
    currencyCode: str  # CurrencyCode!; e.g. "EUR"


@dataclass(config=_CONFIG)
class MoneyBag:
    shopMoney: MoneyV2
    presentmentMoney: MoneyV2 | None = None


# ─── Fulfillment tracking ──────────────────────────────────────────────────


@dataclass(config=_CONFIG)
class FulfillmentTrackingInfo:
    number: str | None = None   # String
    company: str | None = None  # String
    url: str | None = None      # URL scalar (serialised as string in JSON)


@dataclass(config=_CONFIG)
class FulfillmentNode:
    trackingInfo: list[FulfillmentTrackingInfo]  # [FulfillmentTrackingInfo!]!


# ─── order_carrier_catalog_page.gql ───────────────────────────────────────


@dataclass(config=_CONFIG)
class OrderCarrierNode:
    fulfillments: list[FulfillmentNode]  # [Fulfillment!]!


@dataclass(config=_CONFIG)
class OrderCarrierCatalogData:
    orders: Connection[OrderCarrierNode]


# ─── order_by_tracking.gql ────────────────────────────────────────────────


@dataclass(config=_CONFIG)
class MailingAddress:
    address1: str | None = None
    address2: str | None = None
    city: str | None = None
    province: str | None = None
    country: str | None = None
    zip: str | None = None
    countryCodeV2: str | None = None  # CountryCode enum → string


@dataclass(config=_CONFIG)
class CustomerNode:
    firstName: str | None = None  # String (nullable)
    lastName: str | None = None   # String (nullable)


@dataclass(config=_CONFIG)
class ShippingLine:
    title: str                            # String! (non-null)
    originalPriceSet: MoneyBag            # MoneyBag! (non-null)
    discountedPriceSet: MoneyBag | None = None
    carrierIdentifier: str | None = None  # String
    code: str | None = None               # String


@dataclass(config=_CONFIG)
class OrderNode:
    id: str                              # ID!
    name: str                            # String!; e.g. "#1234"
    displayFulfillmentStatus: str        # OrderDisplayFulfillmentStatus! (enum → string)
    fulfillments: list[FulfillmentNode]  # [Fulfillment!]!
    currentTotalPriceSet: MoneyBag       # MoneyBag!
    customer: CustomerNode | None = None
    shippingAddress: MailingAddress | None = None
    totalWeight: int | None = None       # UnsignedInt64 (grams); nullable
    shippingLine: ShippingLine | None = None


@dataclass(config=_CONFIG)
class OrdersByTrackingData:
    orders: Connection[OrderNode]


# ─── API response shapes ──────────────────────────────────────────────────


@dataclass(config=_CONFIG)
class OrderResultAddress(Jsonable):
    address1: str | None = None
    address2: str | None = None
    city: str | None = None
    province: str | None = None
    country: str | None = None
    zip: str | None = None
    countryCode: str | None = None  # from MailingAddress.countryCodeV2


@dataclass(config=_CONFIG)
class OrderResult(Jsonable):
    orderNumber: str
    status: str
    customerName: str
    address: OrderResultAddress | None = None
    weightGrams: int | None = None
    deliveryCost: str | None = None   # formatted via Currency.format_amount
    deliveryTitle: str | None = None  # ShippingLine.title
    orderTotal: str | None = None     # formatted via Currency.format_amount


# ─── Carrier catalog job step results ─────────────────────────────────────


@dataclass(config=_CONFIG)
class OrderCarrierStepPending(Jsonable):
    completed: int
    remaining: int
    total: int
    done: Literal[False] = False
    phase: Literal["order_carrier"] = "order_carrier"


@dataclass(config=_CONFIG)
class OrderCarrierStepDone(Jsonable):
    carriers: list[str]
    completed: int
    total: int
    done: Literal[True] = True
    remaining: int = 0
    phase: Literal["order_carrier"] = "order_carrier"


OrderCarrierStepResult = OrderCarrierStepPending | OrderCarrierStepDone
```

- [ ] **Step 6: Run tests — expect all pass**

```bash
PYTHONPATH=src pytest tests/backend/test_graphqldc_orders.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/backend/pysrc/graphqldc/orders.py tests/__init__.py tests/backend/__init__.py tests/backend/test_graphqldc_orders.py
git commit -m "feat: add order graphql dataclasses and tests"
```

---

### Task 3: Stepped job — `order_carrier_job.py`

**Files:**
- Create: `src/backend/pysrc/order_carrier_job.py`
- Create: `tests/backend/test_order_carrier_job.py`

- [ ] **Step 1: Write failing tests**

Create `tests/backend/test_order_carrier_job.py`:

```python
import pytest
from unittest.mock import patch
from backend.pysrc.order_carrier_job import (
    OrderCarrierJob,
    create_order_carrier_job,
    take_order_carrier_job,
    delete_order_carrier_job,
)
from backend.pysrc.graphqldc.orders import (
    OrderCarrierCatalogData,
    OrderCarrierNode,
    FulfillmentNode,
    FulfillmentTrackingInfo,
    OrderCarrierStepDone,
    OrderCarrierStepPending,
)
from backend.pysrc.graphqldc.common import Connection, Edge, PageInfo


def _make_data(
    companies: list[str | None],
    has_next: bool = False,
    cursor: str | None = None,
) -> OrderCarrierCatalogData:
    """Build OrderCarrierCatalogData with one order per company entry."""
    edges = [
        Edge(
            node=OrderCarrierNode(
                fulfillments=[
                    FulfillmentNode(trackingInfo=[FulfillmentTrackingInfo(company=c)])
                ]
            )
        )
        for c in companies
    ]
    return OrderCarrierCatalogData(
        orders=Connection(
            edges=edges,
            pageInfo=PageInfo(hasNextPage=has_next, endCursor=cursor),
        )
    )


@pytest.fixture
def job():
    return OrderCarrierJob(
        id="test-id",
        shop_domain="test.myshopify.com",
        token="tok",
        max_orders=100,
        date_from=None,
        date_to=None,
    )


def test_step_collects_carriers_and_finishes(job):
    data = _make_data(["DHL", "FedEx", None, "DHL"])  # None + duplicate
    with patch("backend.pysrc.order_carrier_job.GraphQL.send", return_value=data):
        result = job.step()
    assert isinstance(result, OrderCarrierStepDone)
    assert result.done is True
    assert result.carriers == ["DHL", "FedEx"]  # sorted, deduplicated, no None


def test_step_returns_pending_when_more_pages(job):
    data = _make_data(["DHL"] * 250, has_next=True, cursor="cur1")
    with patch("backend.pysrc.order_carrier_job.GraphQL.send", return_value=data):
        result = job.step()
    assert isinstance(result, OrderCarrierStepPending)
    assert result.done is False
    assert job.orders_scanned == 250
    assert job.after == "cur1"


def test_step_stops_at_max_orders():
    job = OrderCarrierJob(
        id="j", shop_domain="s.myshopify.com", token="t",
        max_orders=3, date_from=None, date_to=None
    )
    # hasNextPage True, but 3 scanned >= max_orders=3
    data = _make_data(["A", "B", "C"], has_next=True, cursor="xyz")
    with patch("backend.pysrc.order_carrier_job.GraphQL.send", return_value=data) as mock_send:
        result = job.step()
    assert isinstance(result, OrderCarrierStepDone)
    assert result.done is True
    # Verify batch_size was capped at max_orders=3
    variables = mock_send.call_args.args[3]
    assert variables["first"] == 3


def test_step_passes_date_range_in_query():
    job = OrderCarrierJob(
        id="j", shop_domain="s.myshopify.com", token="t",
        max_orders=10, date_from="2024-01-01", date_to="2024-12-31"
    )
    data = _make_data([])
    with patch("backend.pysrc.order_carrier_job.GraphQL.send", return_value=data) as mock_send:
        job.step()
    variables = mock_send.call_args.args[3]
    assert variables["query"] == "created_at:>=2024-01-01 created_at:<=2024-12-31"


def test_step_no_date_range_passes_none_query(job):
    data = _make_data([])
    with patch("backend.pysrc.order_carrier_job.GraphQL.send", return_value=data) as mock_send:
        job.step()
    variables = mock_send.call_args.args[3]
    assert variables["query"] is None


def test_step_from_only_date():
    job = OrderCarrierJob(
        id="j", shop_domain="s.myshopify.com", token="t",
        max_orders=10, date_from="2024-06-01", date_to=None
    )
    data = _make_data([])
    with patch("backend.pysrc.order_carrier_job.GraphQL.send", return_value=data) as mock_send:
        job.step()
    variables = mock_send.call_args.args[3]
    assert variables["query"] == "created_at:>=2024-06-01"


def test_step_graphql_none_returns_done(job):
    with patch("backend.pysrc.order_carrier_job.GraphQL.send", return_value=None):
        result = job.step()
    assert isinstance(result, OrderCarrierStepDone)
    assert result.carriers == []


def test_finish_returns_sorted_carriers(job):
    job.carriers = {"UPS", "DHL", "FedEx"}
    job.exhausted = True
    result = job.step()
    assert isinstance(result, OrderCarrierStepDone)
    assert result.carriers == ["DHL", "FedEx", "UPS"]


def test_job_registry_create_take_delete():
    jid = create_order_carrier_job("shop.myshopify.com", "tok", 50, None, None)
    assert isinstance(jid, str) and len(jid) > 0
    job = take_order_carrier_job(jid)
    assert job is not None
    assert job.max_orders == 50
    delete_order_carrier_job(jid)
    assert take_order_carrier_job(jid) is None


def test_take_unknown_job_returns_none():
    assert take_order_carrier_job("nonexistent") is None
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
PYTHONPATH=src pytest tests/backend/test_order_carrier_job.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.pysrc.order_carrier_job'`

- [ ] **Step 3: Create `src/backend/pysrc/order_carrier_job.py`**

```python
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

        self.orders_scanned += len(conn.edges)

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
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
PYTHONPATH=src pytest tests/backend/test_order_carrier_job.py -v
```

Expected: all 10 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/backend/pysrc/order_carrier_job.py tests/backend/test_order_carrier_job.py
git commit -m "feat: add order carrier stepped job and tests"
```

---

### Task 4: Lookup function — `order_lookup.py`

**Files:**
- Create: `src/backend/pysrc/order_lookup.py`
- Create: `tests/backend/test_order_lookup.py`

- [ ] **Step 1: Write failing tests**

Create `tests/backend/test_order_lookup.py`:

```python
import pytest
from unittest.mock import patch
from backend.pysrc.order_lookup import lookup_order_by_tracking
from backend.pysrc.graphqldc.orders import (
    OrdersByTrackingData,
    OrderNode,
    FulfillmentNode,
    FulfillmentTrackingInfo,
    MoneyV2,
    MoneyBag,
    CustomerNode,
    MailingAddress,
    ShippingLine,
)
from backend.pysrc.graphqldc.common import Connection, Edge, PageInfo


def _make_money(amount: str, code: str = "EUR") -> MoneyBag:
    return MoneyBag(shopMoney=MoneyV2(amount=amount, currencyCode=code))


def _make_order(
    name: str = "#1001",
    status: str = "FULFILLED",
    carrier: str = "DHL",
    first_name: str | None = "Jane",
    last_name: str | None = "Smith",
    has_address: bool = True,
    weight: int | None = 1200,
    shipping_title: str = "DHL Express",
    shipping_amount: str = "5.90",
    total_amount: str = "49.90",
) -> OrderNode:
    ti = FulfillmentTrackingInfo(company=carrier, number="ABC123", url="https://track.dhl.com")
    customer = CustomerNode(firstName=first_name, lastName=last_name) if (first_name or last_name) else None
    address = MailingAddress(address1="123 Main St", city="Berlin", zip="10115", countryCodeV2="DE") if has_address else None
    sl = ShippingLine(title=shipping_title, originalPriceSet=_make_money(shipping_amount))
    return OrderNode(
        id=f"gid://shopify/Order/1",
        name=name,
        displayFulfillmentStatus=status,
        fulfillments=[FulfillmentNode(trackingInfo=[ti])],
        currentTotalPriceSet=_make_money(total_amount),
        customer=customer,
        shippingAddress=address,
        totalWeight=weight,
        shippingLine=sl,
    )


def _make_parsed(orders: list[OrderNode], has_next: bool = False) -> OrdersByTrackingData:
    edges = [Edge(node=o) for o in orders]
    return OrdersByTrackingData(
        orders=Connection(
            edges=edges,
            pageInfo=PageInfo(hasNextPage=has_next, endCursor=None),
        )
    )


MODULE = "backend.pysrc.order_lookup.GraphQL.send"


def test_basic_lookup_returns_result():
    parsed = _make_parsed([_make_order()])
    with patch(MODULE, return_value=parsed):
        results, warnings = lookup_order_by_tracking("shop.myshopify.com", "tok", "ABC123")
    assert len(results) == 1
    r = results[0]
    assert r.orderNumber == "#1001"
    assert r.status == "FULFILLED"
    assert r.customerName == "Jane Smith"
    assert r.weightGrams == 1200
    assert r.deliveryTitle == "DHL Express"
    assert r.deliveryCost == "5.90 €"
    assert r.orderTotal == "49.90 €"
    assert warnings == []


def test_carrier_filter_case_insensitive():
    orders = [_make_order(name="#1001", carrier="DHL"), _make_order(name="#1002", carrier="FedEx")]
    parsed = _make_parsed(orders)
    with patch(MODULE, return_value=parsed):
        results, _ = lookup_order_by_tracking("s.myshopify.com", "t", "NUM", carrier="fedex")
    assert len(results) == 1
    assert results[0].orderNumber == "#1002"


def test_carrier_filter_none_returns_all():
    orders = [_make_order(name="#1001", carrier="DHL"), _make_order(name="#1002", carrier="FedEx")]
    parsed = _make_parsed(orders)
    with patch(MODULE, return_value=parsed):
        results, _ = lookup_order_by_tracking("s.myshopify.com", "t", "NUM", carrier=None)
    assert len(results) == 2


def test_guest_checkout_customer_name():
    order = _make_order(first_name=None, last_name=None)
    order = OrderNode(
        id=order.id, name=order.name,
        displayFulfillmentStatus=order.displayFulfillmentStatus,
        fulfillments=order.fulfillments,
        currentTotalPriceSet=order.currentTotalPriceSet,
        customer=None,
    )
    parsed = _make_parsed([order])
    with patch(MODULE, return_value=parsed):
        results, _ = lookup_order_by_tracking("s.myshopify.com", "t", "X")
    assert results[0].customerName == "Guest"


def test_no_shipping_line_gives_none_cost():
    order = _make_order()
    order = OrderNode(
        id=order.id, name=order.name,
        displayFulfillmentStatus=order.displayFulfillmentStatus,
        fulfillments=order.fulfillments,
        currentTotalPriceSet=order.currentTotalPriceSet,
        shippingLine=None,
    )
    parsed = _make_parsed([order])
    with patch(MODULE, return_value=parsed):
        results, _ = lookup_order_by_tracking("s.myshopify.com", "t", "X")
    assert results[0].deliveryCost is None
    assert results[0].deliveryTitle is None


def test_has_next_page_adds_warning():
    parsed = _make_parsed([_make_order()], has_next=True)
    with patch(MODULE, return_value=parsed):
        _, warnings = lookup_order_by_tracking("s.myshopify.com", "t", "X")
    assert any("10" in w for w in warnings)


def test_graphql_none_returns_empty_with_warning():
    with patch(MODULE, return_value=None):
        results, warnings = lookup_order_by_tracking("s.myshopify.com", "t", "X")
    assert results == []
    assert len(warnings) == 1


def test_shopify_query_uses_tracking_number():
    parsed = _make_parsed([])
    with patch(MODULE, return_value=parsed) as mock_send:
        lookup_order_by_tracking("s.myshopify.com", "t", "1Z999AA10123456784")
    variables = mock_send.call_args.args[3]
    assert variables["query"] == "tracking_number:1Z999AA10123456784"


def test_address_mapped_correctly():
    parsed = _make_parsed([_make_order(has_address=True)])
    with patch(MODULE, return_value=parsed):
        results, _ = lookup_order_by_tracking("s.myshopify.com", "t", "X")
    addr = results[0].address
    assert addr is not None
    assert addr.city == "Berlin"
    assert addr.countryCode == "DE"
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
PYTHONPATH=src pytest tests/backend/test_order_lookup.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.pysrc.order_lookup'`

- [ ] **Step 3: Create `src/backend/pysrc/order_lookup.py`**

```python
from __future__ import annotations

from .fileloader import FileLoader
from .graphql import GraphQL
from .graphqldc.orders import (
    OrderResult,
    OrderResultAddress,
    OrdersByTrackingData,
)
from .symbols import Currency


def lookup_order_by_tracking(
    shop_domain: str,
    token: str,
    tracking_number: str,
    carrier: str | None = None,
) -> tuple[list[OrderResult], list[str]]:
    query = FileLoader.load("order_by_tracking.gql")
    parsed = GraphQL.send(
        shop_domain,
        token,
        query,
        {"query": f"tracking_number:{tracking_number}"},
        expected_type=OrdersByTrackingData,
    )

    warnings: list[str] = []
    if parsed is None:
        return [], ["Could not parse order lookup response."]

    conn = parsed.orders
    nodes = [edge.node for edge in conn.edges]

    if conn.pageInfo.hasNextPage:
        warnings.append("More than 10 results — refine your search.")

    if carrier:
        carrier_lower = carrier.lower()
        nodes = [
            n for n in nodes
            if any(
                ti.company and ti.company.lower() == carrier_lower
                for f in n.fulfillments
                for ti in f.trackingInfo
            )
        ]

    results: list[OrderResult] = []
    for node in nodes:
        c = node.customer
        if c:
            parts = [p for p in [c.firstName, c.lastName] if p]
            customer_name = " ".join(parts) or "Guest"
        else:
            customer_name = "Guest"

        address: OrderResultAddress | None = None
        if node.shippingAddress:
            a = node.shippingAddress
            address = OrderResultAddress(
                address1=a.address1,
                address2=a.address2,
                city=a.city,
                province=a.province,
                country=a.country,
                zip=a.zip,
                countryCode=a.countryCodeV2,
            )

        delivery_cost: str | None = None
        delivery_title: str | None = None
        if node.shippingLine:
            delivery_title = node.shippingLine.title
            m = node.shippingLine.originalPriceSet.shopMoney
            delivery_cost = Currency.format_amount(m.amount, m.currencyCode)

        m_total = node.currentTotalPriceSet.shopMoney
        order_total = Currency.format_amount(m_total.amount, m_total.currencyCode)

        results.append(OrderResult(
            orderNumber=node.name,
            status=node.displayFulfillmentStatus,
            customerName=customer_name,
            address=address,
            weightGrams=node.totalWeight,
            deliveryCost=delivery_cost,
            deliveryTitle=delivery_title,
            orderTotal=order_total,
        ))

    return results, warnings
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
PYTHONPATH=src pytest tests/backend/test_order_lookup.py -v
```

Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/backend/pysrc/order_lookup.py tests/backend/test_order_lookup.py
git commit -m "feat: add order tracking lookup function and tests"
```

---

### Task 5: Flask routes

**Files:**
- Modify: `src/backend/pysrc/routes.py`
- Modify: `src/backend/main.py`
- Create: `tests/backend/test_order_routes.py`

- [ ] **Step 1: Write failing route tests**

Create `tests/backend/test_order_routes.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from backend.main import application
from backend.pysrc.graphqldc.orders import OrderCarrierStepDone, OrderCarrierStepPending, OrderResult


@pytest.fixture
def client():
    application.config["TESTING"] = True
    with application.test_client() as c:
        yield c


# Patch targets — these are set by protect_api / sync_mutation_allow_to_g before_request hooks.
_SECURITY_PATCHES = {
    "backend.pysrc.security.Security.get_session_token": "fake-session-token",
    "backend.pysrc.security.Security.get_shop_domain": "test.myshopify.com",
    "backend.pysrc.database.Database.MutationAllow.get_allow": False,
}


def _auth_patches():
    return [
        patch(k, return_value=v)
        for k, v in _SECURITY_PATCHES.items()
    ]


# ── /api/order-carrier-catalog/start ────────────────────────────────────────

def test_carrier_start_no_token_returns_401(client):
    with patch("backend.pysrc.security.Security.get_session_token", return_value="t"), \
         patch("backend.pysrc.security.Security.get_shop_domain", return_value="shop.myshopify.com"), \
         patch("backend.pysrc.database.Database.MutationAllow.get_allow", return_value=False), \
         patch("backend.pysrc.database.Database.AccessTokens.get_token", return_value=None):
        resp = client.post("/api/order-carrier-catalog/start", json={})
    assert resp.status_code == 401


def test_carrier_start_creates_job(client):
    with patch("backend.pysrc.security.Security.get_session_token", return_value="t"), \
         patch("backend.pysrc.security.Security.get_shop_domain", return_value="shop.myshopify.com"), \
         patch("backend.pysrc.database.Database.MutationAllow.get_allow", return_value=False), \
         patch("backend.pysrc.database.Database.AccessTokens.get_token", return_value="access-tok"), \
         patch("backend.main.create_order_carrier_job", return_value="job-abc") as mock_create:
        resp = client.post(
            "/api/order-carrier-catalog/start",
            json={"maxOrders": 500, "dateFrom": "2024-01-01", "dateTo": "2024-12-31"},
        )
    assert resp.status_code == 200
    assert resp.get_json()["jobId"] == "job-abc"
    mock_create.assert_called_once_with("shop.myshopify.com", "access-tok", 500, "2024-01-01", "2024-12-31")


def test_carrier_start_clamps_max_orders(client):
    with patch("backend.pysrc.security.Security.get_session_token", return_value="t"), \
         patch("backend.pysrc.security.Security.get_shop_domain", return_value="shop.myshopify.com"), \
         patch("backend.pysrc.database.Database.MutationAllow.get_allow", return_value=False), \
         patch("backend.pysrc.database.Database.AccessTokens.get_token", return_value="tok"), \
         patch("backend.main.create_order_carrier_job", return_value="jid") as mock_create:
        client.post("/api/order-carrier-catalog/start", json={"maxOrders": 99999})
    _, _, max_orders, _, _ = mock_create.call_args.args
    assert max_orders == 10000  # clamped


def test_carrier_start_defaults_max_orders(client):
    with patch("backend.pysrc.security.Security.get_session_token", return_value="t"), \
         patch("backend.pysrc.security.Security.get_shop_domain", return_value="shop.myshopify.com"), \
         patch("backend.pysrc.database.Database.MutationAllow.get_allow", return_value=False), \
         patch("backend.pysrc.database.Database.AccessTokens.get_token", return_value="tok"), \
         patch("backend.main.create_order_carrier_job", return_value="jid") as mock_create:
        client.post("/api/order-carrier-catalog/start", json={})
    _, _, max_orders, _, _ = mock_create.call_args.args
    assert max_orders == 1000  # default


# ── /api/order-carrier-catalog/step ─────────────────────────────────────────

def test_carrier_step_missing_job_id_returns_400(client):
    with patch("backend.pysrc.security.Security.get_session_token", return_value="t"), \
         patch("backend.pysrc.security.Security.get_shop_domain", return_value="shop.myshopify.com"), \
         patch("backend.pysrc.database.Database.MutationAllow.get_allow", return_value=False), \
         patch("backend.pysrc.database.Database.AccessTokens.get_token", return_value="tok"):
        resp = client.post("/api/order-carrier-catalog/step", json={})
    assert resp.status_code == 400


def test_carrier_step_unknown_job_returns_404(client):
    with patch("backend.pysrc.security.Security.get_session_token", return_value="t"), \
         patch("backend.pysrc.security.Security.get_shop_domain", return_value="shop.myshopify.com"), \
         patch("backend.pysrc.database.Database.MutationAllow.get_allow", return_value=False), \
         patch("backend.pysrc.database.Database.AccessTokens.get_token", return_value="tok"), \
         patch("backend.main.take_order_carrier_job", return_value=None):
        resp = client.post("/api/order-carrier-catalog/step", json={"jobId": "unknown"})
    assert resp.status_code == 404


def test_carrier_step_done_deletes_job(client):
    done = OrderCarrierStepDone(carriers=["DHL"], completed=1, total=1)
    mock_job = MagicMock()
    mock_job.step.return_value = done
    with patch("backend.pysrc.security.Security.get_session_token", return_value="t"), \
         patch("backend.pysrc.security.Security.get_shop_domain", return_value="shop.myshopify.com"), \
         patch("backend.pysrc.database.Database.MutationAllow.get_allow", return_value=False), \
         patch("backend.pysrc.database.Database.AccessTokens.get_token", return_value="tok"), \
         patch("backend.main.take_order_carrier_job", return_value=mock_job), \
         patch("backend.main.delete_order_carrier_job") as mock_delete:
        resp = client.post("/api/order-carrier-catalog/step", json={"jobId": "job1"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["done"] is True
    assert data["carriers"] == ["DHL"]
    mock_delete.assert_called_once_with("job1")


# ── /api/order-by-tracking ──────────────────────────────────────────────────

def test_order_lookup_missing_tracking_number(client):
    with patch("backend.pysrc.security.Security.get_session_token", return_value="t"), \
         patch("backend.pysrc.security.Security.get_shop_domain", return_value="shop.myshopify.com"), \
         patch("backend.pysrc.database.Database.MutationAllow.get_allow", return_value=False), \
         patch("backend.pysrc.database.Database.AccessTokens.get_token", return_value="tok"):
        resp = client.get("/api/order-by-tracking")
    assert resp.status_code == 400


def test_order_lookup_returns_orders(client):
    result = OrderResult(orderNumber="#1001", status="FULFILLED", customerName="Jane Smith", orderTotal="€49.90")
    with patch("backend.pysrc.security.Security.get_session_token", return_value="t"), \
         patch("backend.pysrc.security.Security.get_shop_domain", return_value="shop.myshopify.com"), \
         patch("backend.pysrc.database.Database.MutationAllow.get_allow", return_value=False), \
         patch("backend.pysrc.database.Database.AccessTokens.get_token", return_value="tok"), \
         patch("backend.main.lookup_order_by_tracking", return_value=([result], [])):
        resp = client.get("/api/order-by-tracking?trackingNumber=ABC123")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["orders"][0]["orderNumber"] == "#1001"
    assert data["warnings"] == []


def test_order_lookup_passes_carrier(client):
    with patch("backend.pysrc.security.Security.get_session_token", return_value="t"), \
         patch("backend.pysrc.security.Security.get_shop_domain", return_value="shop.myshopify.com"), \
         patch("backend.pysrc.database.Database.MutationAllow.get_allow", return_value=False), \
         patch("backend.pysrc.database.Database.AccessTokens.get_token", return_value="tok"), \
         patch("backend.main.lookup_order_by_tracking", return_value=([], [])) as mock_lookup:
        client.get("/api/order-by-tracking?trackingNumber=X&carrier=DHL")
    mock_lookup.assert_called_once_with("shop.myshopify.com", "tok", "X", "DHL")
```

- [ ] **Step 2: Run tests — expect errors (routes don't exist yet)**

```bash
PYTHONPATH=src pytest tests/backend/test_order_routes.py -v
```

Expected: failures due to missing routes and imports.

- [ ] **Step 3: Add routes to `src/backend/pysrc/routes.py`**

Add these three lines inside the `Routes` class (after the existing `GRAPHQL_MUTATION_ALLOW` line):

```python
    ORDER_CARRIER_CATALOG_START = f"{API}/order-carrier-catalog/start"
    ORDER_CARRIER_CATALOG_STEP  = f"{API}/order-carrier-catalog/step"
    ORDER_BY_TRACKING           = f"{API}/order-by-tracking"
```

- [ ] **Step 4: Add imports to `src/backend/main.py`**

Add these imports at the top of `main.py`, alongside the existing import block:

```python
from backend.pysrc.order_carrier_job import (
    create_order_carrier_job,
    delete_order_carrier_job,
    take_order_carrier_job,
)
from backend.pysrc.order_lookup import lookup_order_by_tracking
```

- [ ] **Step 5: Add three route handlers to `src/backend/main.py`**

Add before the final `@application.route("/")` handler:

```python
@application.route(Routes.ORDER_CARRIER_CATALOG_START, methods=["POST"])
def order_carrier_catalog_start():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({"error": "Not installed"}), 401
    raw_body = cast(Json.Value, flask.request.get_json(silent=True))
    body = raw_body if isinstance(raw_body, dict) else {}
    date_from_raw = body.get("dateFrom")
    date_to_raw = body.get("dateTo")
    max_orders_raw = body.get("maxOrders", 1000)
    date_from = (
        date_from_raw.strip()
        if isinstance(date_from_raw, str) and date_from_raw.strip()
        else None
    )
    date_to = (
        date_to_raw.strip()
        if isinstance(date_to_raw, str) and date_to_raw.strip()
        else None
    )
    try:
        max_orders = max(1, min(10000, int(max_orders_raw)))
    except (TypeError, ValueError):
        max_orders = 1000
    jid = create_order_carrier_job(Server.shop_domain, token, max_orders, date_from, date_to)
    return flask.jsonify({"jobId": jid})


@application.route(Routes.ORDER_CARRIER_CATALOG_STEP, methods=["POST"])
def order_carrier_catalog_step():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({"error": "Not installed"}), 401
    raw_body = cast(Json.Value, flask.request.get_json(silent=True))
    body = raw_body if isinstance(raw_body, dict) else {}
    job_id = body.get("jobId")
    if not isinstance(job_id, str) or not job_id.strip():
        return flask.jsonify({"error": "Missing jobId"}), 400
    job = take_order_carrier_job(job_id.strip())
    if job is None:
        return flask.jsonify({"error": "Unknown or expired job"}), 404
    try:
        result = job.step()
    except RuntimeError as e:
        return flask.jsonify({"error": str(e)}), 502
    flask.g.graphql_phase_total = result.total
    flask.g.graphql_phase_done = result.completed
    if result.done:
        delete_order_carrier_job(job_id.strip())
    return flask.jsonify(result.to_json())


@application.route(Routes.ORDER_BY_TRACKING, methods=["GET"])
def order_by_tracking():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({"error": "Not installed"}), 401
    tracking_number = flask.request.args.get("trackingNumber", "").strip()
    if not tracking_number:
        return flask.jsonify({"error": "Missing trackingNumber"}), 400
    carrier_raw = flask.request.args.get("carrier", "").strip()
    carrier = carrier_raw if carrier_raw else None
    try:
        results, warnings = lookup_order_by_tracking(
            Server.shop_domain, token, tracking_number, carrier
        )
        return flask.jsonify({
            "orders": [r.to_json() for r in results],
            "warnings": warnings,
        })
    except RuntimeError as e:
        return flask.jsonify({"error": str(e)}), 502
```

- [ ] **Step 6: Run all tests — expect all pass**

```bash
PYTHONPATH=src pytest tests/ -v
```

Expected: all tests across all four test files pass.

- [ ] **Step 7: Commit**

```bash
git add src/backend/pysrc/routes.py src/backend/main.py tests/backend/test_order_routes.py
git commit -m "feat: add order lookup Flask routes and tests"
```

---

### Task 6: CSS + build wiring

**Files:**
- Create: `src/frontend/styles/order-lookup.css`
- Modify: `esbuild.mjs`
- Modify: `src/frontend/templates/index.html`

- [ ] **Step 1: Create `src/frontend/styles/order-lookup.css`**

```css
.order-lookup {
    max-width: min(900px, 100%);
    margin: 0 auto;
    padding: 1.5rem 1rem 2rem;
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    color: #1a1a1a;
}

.order-lookup__title {
    font-size: 1.125rem;
    font-weight: 600;
    margin: 0 0 1.25rem;
    letter-spacing: -0.01em;
}

/* ── Carrier loader ─────────────────────────────────────────────── */

.order-lookup__loader {
    margin-bottom: 1.75rem;
    padding-bottom: 1.75rem;
    border-bottom: 1px solid #e2e8f0;
}

.order-lookup__loader-row {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 0.75rem 1rem;
    margin-bottom: 0.75rem;
}

.order-lookup__field {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
}

.order-lookup__field label {
    font-size: 0.8125rem;
    font-weight: 500;
    color: #475569;
}

.order-lookup__field input,
.order-lookup__field select {
    font: inherit;
    font-size: 0.875rem;
    padding: 0.35rem 0.6rem;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #fff;
    color: #1a1a1a;
    min-width: 9rem;
}

.order-lookup__field input:focus,
.order-lookup__field select:focus {
    outline: 2px solid #2563eb;
    outline-offset: 1px;
}

.order-lookup__field--narrow input {
    width: 7rem;
}

.order-lookup__refresh-btn {
    font: inherit;
    font-size: 0.875rem;
    font-weight: 500;
    padding: 0.4rem 1rem;
    border: 1px solid #2563eb;
    border-radius: 6px;
    background: #2563eb;
    color: #fff;
    cursor: pointer;
    white-space: nowrap;
    align-self: flex-end;
}

.order-lookup__refresh-btn:disabled {
    opacity: 0.55;
    cursor: not-allowed;
}

.order-lookup__refresh-btn:not(:disabled):hover {
    background: #1d4ed8;
    border-color: #1d4ed8;
}

.order-lookup__progress {
    font-size: 0.8125rem;
    color: #64748b;
    margin: 0.5rem 0 0;
}

.order-lookup__carrier-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-top: 0.75rem;
}

.order-lookup__carrier-row label {
    font-size: 0.8125rem;
    font-weight: 500;
    color: #475569;
    white-space: nowrap;
}

/* ── Tracking lookup ────────────────────────────────────────────── */

.order-lookup__search-row {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 0.75rem 1rem;
    margin-bottom: 1rem;
}

.order-lookup__tracking-input {
    font: inherit;
    font-size: 0.875rem;
    padding: 0.4rem 0.65rem;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #fff;
    color: #1a1a1a;
    width: 22rem;
    max-width: 100%;
}

.order-lookup__tracking-input:focus {
    outline: 2px solid #2563eb;
    outline-offset: 1px;
}

.order-lookup__lookup-btn {
    font: inherit;
    font-size: 0.875rem;
    font-weight: 500;
    padding: 0.4rem 1.1rem;
    border: 1px solid #0f172a;
    border-radius: 6px;
    background: #0f172a;
    color: #fff;
    cursor: pointer;
}

.order-lookup__lookup-btn:disabled {
    opacity: 0.55;
    cursor: not-allowed;
}

.order-lookup__lookup-btn:not(:disabled):hover {
    background: #1e293b;
    border-color: #1e293b;
}

.order-lookup__inline-msg {
    font-size: 0.8125rem;
    color: #64748b;
    margin: 0 0 0.5rem;
}

.order-lookup__inline-msg--error {
    color: #b91c1c;
}

/* ── Result cards ───────────────────────────────────────────────── */

.order-lookup__results {
    display: flex;
    flex-direction: column;
    gap: 1rem;
}

.order-lookup__card {
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 1rem 1.25rem;
    background: #f8fafc;
}

.order-lookup__card-header {
    display: flex;
    align-items: baseline;
    gap: 0.75rem;
    margin-bottom: 0.75rem;
}

.order-lookup__card-order-number {
    font-size: 1rem;
    font-weight: 600;
    color: #0f172a;
}

.order-lookup__card-status {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #64748b;
    background: #e2e8f0;
    border-radius: 4px;
    padding: 0.15rem 0.45rem;
}

.order-lookup__card-row {
    display: grid;
    grid-template-columns: 8rem 1fr;
    gap: 0.15rem 0.5rem;
    font-size: 0.875rem;
    line-height: 1.5;
}

.order-lookup__card-label {
    color: #64748b;
    font-weight: 500;
}

.order-lookup__card-value {
    color: #1a1a1a;
}
```

- [ ] **Step 2: Add CSS copy to `esbuild.mjs`**

In `esbuild.mjs`, inside the `.then(() => { ... })` block, add after the last `copyFileSync` call:

```js
    fs.copyFileSync(
        "src/frontend/styles/order-lookup.css",
        "dist/order-lookup.css"
    )
```

- [ ] **Step 3: Add `<link>` tag to `src/frontend/templates/index.html`**

Add after the existing `shipping-rates.css` link:

```html
    <link rel="stylesheet" href="{{ url_for('static', filename='order-lookup.css') }}" />
```

- [ ] **Step 4: Commit**

```bash
git add src/frontend/styles/order-lookup.css esbuild.mjs src/frontend/templates/index.html
git commit -m "feat: add order-lookup CSS and wire into build"
```

---

### Task 7: Frontend panel — `OrderLookupPanel.tsx`

**Files:**
- Create: `src/frontend/tsxsrc/OrderLookupPanel.tsx`

- [ ] **Step 1: Create `src/frontend/tsxsrc/OrderLookupPanel.tsx`**

```tsx
import { ReactNode, useState } from "react"
import AppBridge from "../tssrc/app_bridge"
import { runSteppedCatalogJob } from "../tssrc/catalog_job"

// ─── API shape types ───────────────────────────────────────────────────────

interface CarrierDoneResponse {
    done: true
    carriers: string[]
}

interface OrderAddress {
    address1?: string | null
    address2?: string | null
    city?: string | null
    province?: string | null
    country?: string | null
    zip?: string | null
    countryCode?: string | null
}

interface OrderResult {
    orderNumber: string
    status: string
    customerName: string
    address?: OrderAddress | null
    weightGrams?: number | null
    deliveryCost?: string | null
    deliveryTitle?: string | null
    orderTotal?: string | null
}

interface LookupResponse {
    orders: OrderResult[]
    warnings?: string[]
    error?: string
}

// ─── Helpers ───────────────────────────────────────────────────────────────

async function readJsonBody<T>(res: Response): Promise<T | null> {
    const text = await res.text()
    const trimmed = text.trimStart()
    if (trimmed === "" || trimmed.startsWith("<")) return null
    try {
        return JSON.parse(text) as T
    } catch {
        return null
    }
}

function formatAddress(addr: OrderAddress): string {
    return [
        addr.address1,
        addr.address2,
        addr.city,
        addr.province,
        addr.zip,
        addr.country ?? addr.countryCode,
    ]
        .filter(Boolean)
        .join(", ")
}

// ─── Component ─────────────────────────────────────────────────────────────

export default function OrderLookupPanel(): ReactNode {
    // Carrier loader
    const [dateFrom, setDateFrom] = useState("")
    const [dateTo, setDateTo] = useState("")
    const [maxOrders, setMaxOrders] = useState("1000")
    const [loadingCarriers, setLoadingCarriers] = useState(false)
    const [carriers, setCarriers] = useState<string[]>([])
    const [selectedCarrier, setSelectedCarrier] = useState("")
    const [carrierError, setCarrierError] = useState<string | null>(null)

    // Tracking lookup
    const [trackingNumber, setTrackingNumber] = useState("")
    const [lookupLoading, setLookupLoading] = useState(false)
    const [orders, setOrders] = useState<OrderResult[] | null>(null)
    const [lookupError, setLookupError] = useState<string | null>(null)
    const [lookupWarnings, setLookupWarnings] = useState<string[]>([])

    async function onRefreshCarriers(): Promise<void> {
        setLoadingCarriers(true)
        setCarriers([])
        setSelectedCarrier("")
        setCarrierError(null)
        try {
            const body: Record<string, unknown> = {
                maxOrders: Math.max(1, Number(maxOrders) || 1000),
            }
            if (dateFrom) body.dateFrom = dateFrom
            if (dateTo) body.dateTo = dateTo
            const result = await runSteppedCatalogJob(
                "/api/order-carrier-catalog/start",
                "/api/order-carrier-catalog/step",
                body,
            )
            const data = result as unknown as CarrierDoneResponse
            setCarriers(data.carriers ?? [])
        } catch (e) {
            setCarrierError(
                e instanceof Error ? e.message : "Could not load carrier list."
            )
        } finally {
            setLoadingCarriers(false)
        }
    }

    async function onLookup(): Promise<void> {
        const tn = trackingNumber.trim()
        if (!tn) return
        setLookupLoading(true)
        setOrders(null)
        setLookupError(null)
        setLookupWarnings([])
        try {
            const q = new URLSearchParams({ trackingNumber: tn })
            if (selectedCarrier) q.set("carrier", selectedCarrier)
            const res = await AppBridge.fetchWithToken(
                `/api/order-by-tracking?${q.toString()}`
            )
            const data = await readJsonBody<LookupResponse>(res)
            if (!res.ok) {
                setLookupError(data?.error ?? `Lookup failed (${res.status}).`)
                return
            }
            if (!data) {
                setLookupError("Could not read server response.")
                return
            }
            setOrders(data.orders ?? [])
            setLookupWarnings(data.warnings ?? [])
        } catch (e) {
            setLookupError(e instanceof Error ? e.message : "Lookup failed.")
        } finally {
            setLookupLoading(false)
        }
    }

    return (
        <section className="order-lookup" aria-labelledby="order-lookup-heading">
            <h2 id="order-lookup-heading" className="order-lookup__title">
                Order lookup by tracking number
            </h2>

            {/* ── Carrier loader ── */}
            <div className="order-lookup__loader">
                <div className="order-lookup__loader-row">
                    <div className="order-lookup__field">
                        <label htmlFor="ol-date-from">From date</label>
                        <input
                            id="ol-date-from"
                            type="date"
                            value={dateFrom}
                            onChange={(e) => setDateFrom(e.target.value)}
                            disabled={loadingCarriers}
                        />
                    </div>
                    <div className="order-lookup__field">
                        <label htmlFor="ol-date-to">To date</label>
                        <input
                            id="ol-date-to"
                            type="date"
                            value={dateTo}
                            onChange={(e) => setDateTo(e.target.value)}
                            disabled={loadingCarriers}
                        />
                    </div>
                    <div className="order-lookup__field order-lookup__field--narrow">
                        <label htmlFor="ol-max-orders">Max orders</label>
                        <input
                            id="ol-max-orders"
                            type="number"
                            min={1}
                            max={10000}
                            value={maxOrders}
                            onChange={(e) => setMaxOrders(e.target.value)}
                            disabled={loadingCarriers}
                        />
                    </div>
                    <button
                        type="button"
                        className="order-lookup__refresh-btn"
                        onClick={() => void onRefreshCarriers()}
                        disabled={loadingCarriers}
                    >
                        {loadingCarriers ? "Loading…" : "Refresh ↺"}
                    </button>
                </div>
                {loadingCarriers ? (
                    <p className="order-lookup__progress" role="status">
                        Scanning orders for carriers…
                    </p>
                ) : null}
                {carrierError ? (
                    <p className="order-lookup__inline-msg order-lookup__inline-msg--error">
                        {carrierError}
                    </p>
                ) : null}
                <div className="order-lookup__carrier-row">
                    <label htmlFor="ol-carrier">Carrier</label>
                    <select
                        id="ol-carrier"
                        value={selectedCarrier}
                        onChange={(e) => setSelectedCarrier(e.target.value)}
                        disabled={loadingCarriers || carriers.length === 0}
                    >
                        <option value="">All</option>
                        {carriers.map((c) => (
                            <option key={c} value={c}>
                                {c}
                            </option>
                        ))}
                    </select>
                </div>
            </div>

            {/* ── Tracking lookup ── */}
            <div className="order-lookup__search-row">
                <input
                    className="order-lookup__tracking-input"
                    type="text"
                    placeholder="Enter tracking number"
                    autoComplete="off"
                    value={trackingNumber}
                    onChange={(e) => setTrackingNumber(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === "Enter") void onLookup()
                    }}
                    disabled={lookupLoading}
                    aria-label="Tracking number"
                />
                <button
                    type="button"
                    className="order-lookup__lookup-btn"
                    onClick={() => void onLookup()}
                    disabled={lookupLoading || !trackingNumber.trim()}
                >
                    {lookupLoading ? "Looking up…" : "Look up"}
                </button>
            </div>

            {lookupWarnings.map((w) => (
                <p key={w} className="order-lookup__inline-msg">
                    {w}
                </p>
            ))}
            {lookupError ? (
                <p className="order-lookup__inline-msg order-lookup__inline-msg--error" role="alert">
                    {lookupError}
                </p>
            ) : null}

            {/* ── Results ── */}
            {orders !== null ? (
                orders.length === 0 ? (
                    <p className="order-lookup__inline-msg">No orders found.</p>
                ) : (
                    <div className="order-lookup__results">
                        {orders.map((order) => (
                            <div key={order.orderNumber} className="order-lookup__card">
                                <div className="order-lookup__card-header">
                                    <span className="order-lookup__card-order-number">
                                        {order.orderNumber}
                                    </span>
                                    <span className="order-lookup__card-status">
                                        {order.status.replace(/_/g, " ")}
                                    </span>
                                </div>
                                <div className="order-lookup__card-row">
                                    <span className="order-lookup__card-label">Customer</span>
                                    <span className="order-lookup__card-value">
                                        {order.customerName}
                                    </span>
                                    {order.address ? (
                                        <>
                                            <span className="order-lookup__card-label">Address</span>
                                            <span className="order-lookup__card-value">
                                                {formatAddress(order.address)}
                                            </span>
                                        </>
                                    ) : null}
                                    {order.weightGrams != null ? (
                                        <>
                                            <span className="order-lookup__card-label">Weight</span>
                                            <span className="order-lookup__card-value">
                                                {order.weightGrams.toLocaleString()} g
                                            </span>
                                        </>
                                    ) : null}
                                    {order.deliveryCost != null ? (
                                        <>
                                            <span className="order-lookup__card-label">Delivery</span>
                                            <span className="order-lookup__card-value">
                                                {order.deliveryCost}
                                                {order.deliveryTitle
                                                    ? ` (${order.deliveryTitle})`
                                                    : null}
                                            </span>
                                        </>
                                    ) : null}
                                    <span className="order-lookup__card-label">Total</span>
                                    <span className="order-lookup__card-value">
                                        {order.orderTotal ?? "—"}
                                    </span>
                                </div>
                            </div>
                        ))}
                    </div>
                )
            ) : null}
        </section>
    )
}
```

- [ ] **Step 2: Commit**

```bash
git add src/frontend/tsxsrc/OrderLookupPanel.tsx
git commit -m "feat: add OrderLookupPanel component"
```

---

### Task 8: Wire up the third tab in `app.tsx`

**Files:**
- Modify: `src/frontend/tsxsrc/app.tsx`

- [ ] **Step 1: Update `src/frontend/tsxsrc/app.tsx`**

Replace the entire file with:

```tsx
import { ReactNode, useState } from "react"
import GraphqlStatsBar from "./GraphqlStatsBar"
import OrderLookupPanel from "./OrderLookupPanel"
import ProductTagPricingPanel from "./ProductTagPricingPanel"
import ShippingRatesPanel from "./ShippingRatesPanel"

type TabId = "shipping" | "products" | "orders"

export default function App(): ReactNode {
    const [tab, setTab] = useState<TabId>("shipping")

    return (
        <main>
            <GraphqlStatsBar />
            <div className="app-tabs">
                <div className="app-tabs__bar" role="tablist" aria-label="Pricing tools">
                    <button
                        type="button"
                        role="tab"
                        id="tab-shipping"
                        className={
                            tab === "shipping"
                                ? "app-tabs__tab app-tabs__tab--active"
                                : "app-tabs__tab"
                        }
                        aria-selected={tab === "shipping"}
                        aria-controls="panel-shipping"
                        onClick={() => setTab("shipping")}
                    >
                        Delivery rates
                    </button>
                    <button
                        type="button"
                        role="tab"
                        id="tab-products"
                        className={
                            tab === "products"
                                ? "app-tabs__tab app-tabs__tab--active"
                                : "app-tabs__tab"
                        }
                        aria-selected={tab === "products"}
                        aria-controls="panel-products"
                        onClick={() => setTab("products")}
                    >
                        Product tag prices
                    </button>
                    <button
                        type="button"
                        role="tab"
                        id="tab-orders"
                        className={
                            tab === "orders"
                                ? "app-tabs__tab app-tabs__tab--active"
                                : "app-tabs__tab"
                        }
                        aria-selected={tab === "orders"}
                        aria-controls="panel-orders"
                        onClick={() => setTab("orders")}
                    >
                        Order lookup
                    </button>
                </div>
                <div
                    id="panel-shipping"
                    role="tabpanel"
                    className="app-tabs__panel"
                    aria-labelledby="tab-shipping"
                    hidden={tab !== "shipping"}
                >
                    <ShippingRatesPanel />
                </div>
                <div
                    id="panel-products"
                    role="tabpanel"
                    className="app-tabs__panel"
                    aria-labelledby="tab-products"
                    hidden={tab !== "products"}
                >
                    <ProductTagPricingPanel />
                </div>
                <div
                    id="panel-orders"
                    role="tabpanel"
                    className="app-tabs__panel"
                    aria-labelledby="tab-orders"
                    hidden={tab !== "orders"}
                >
                    <OrderLookupPanel />
                </div>
            </div>
        </main>
    )
}
```

- [ ] **Step 2: Run all backend tests one final time**

```bash
PYTHONPATH=src pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 3: Build the frontend to verify no TypeScript errors**

```bash
node esbuild.mjs
```

Expected: `dist/script.js` and `dist/order-lookup.css` produced with no errors.

- [ ] **Step 4: Commit**

```bash
git add src/frontend/tsxsrc/app.tsx
git commit -m "feat: wire Order lookup tab into app"
```
