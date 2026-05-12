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
    assert "address" not in j
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
    assert "address2" not in j["address"]


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
