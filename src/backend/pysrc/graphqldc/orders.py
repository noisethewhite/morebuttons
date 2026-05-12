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
