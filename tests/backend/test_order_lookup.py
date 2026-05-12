from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from backend.pysrc.graphqldc.common import Connection, Edge, PageInfo
from backend.pysrc.graphqldc.orders import (
    CustomerNode,
    FulfillmentNode,
    FulfillmentTrackingInfo,
    MailingAddress,
    MoneyBag,
    MoneyV2,
    OrderNode,
    OrdersByTrackingData,
    ShippingLine,
)
from backend.pysrc.order_lookup import lookup_order_by_tracking


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_money(amount: str, currency: str = "EUR") -> MoneyBag:
    return MoneyBag(shopMoney=MoneyV2(amount=amount, currencyCode=currency))


def _make_order(
    name: str = "#1001",
    status: str = "FULFILLED",
    customer: CustomerNode | None = CustomerNode(firstName="Jane", lastName="Smith"),
    fulfillments: list[FulfillmentNode] | None = None,
    shipping_address: MailingAddress | None = None,
    total_weight: int | None = 1200,
    shipping_line: ShippingLine | None = None,
    total_price_amount: str = "49.90",
    total_price_currency: str = "EUR",
) -> OrderNode:
    if fulfillments is None:
        fulfillments = [
            FulfillmentNode(
                trackingInfo=[FulfillmentTrackingInfo(company="DHL", number="ABC123")]
            )
        ]
    return OrderNode(
        id="gid://shopify/Order/1",
        name=name,
        displayFulfillmentStatus=status,
        fulfillments=fulfillments,
        currentTotalPriceSet=_make_money(total_price_amount, total_price_currency),
        customer=customer,
        shippingAddress=shipping_address,
        totalWeight=total_weight,
        shippingLine=shipping_line,
    )


def _make_parsed(
    nodes: list[OrderNode],
    has_next_page: bool = False,
) -> OrdersByTrackingData:
    edges = [Edge(node=n) for n in nodes]
    conn: Connection[OrderNode] = Connection(
        edges=edges,
        pageInfo=PageInfo(hasNextPage=has_next_page),
    )
    return OrdersByTrackingData(orders=conn)


# ── Tests ─────────────────────────────────────────────────────────────────────

PATCH_TARGET = "backend.pysrc.order_lookup.GraphQL.send"


def test_basic_lookup_returns_result():
    shipping_line = ShippingLine(
        title="DHL Express",
        originalPriceSet=_make_money("5.90", "EUR"),
    )
    node = _make_order(
        shipping_address=MailingAddress(
            address1="123 Main St", city="Berlin", zip="10115",
            country="Germany", countryCodeV2="DE"
        ),
        shipping_line=shipping_line,
    )
    parsed = _make_parsed([node])

    with patch(PATCH_TARGET, return_value=parsed):
        results, warnings = lookup_order_by_tracking("shop.myshopify.com", "token", "ABC123")

    assert len(results) == 1
    assert warnings == []
    r = results[0]
    assert r.orderNumber == "#1001"
    assert r.status == "FULFILLED"
    assert r.customerName == "Jane Smith"
    assert r.weightGrams == 1200
    assert r.deliveryTitle == "DHL Express"
    assert r.deliveryCost == "5.90 EUR"
    assert r.orderTotal == "49.90 EUR"


def test_carrier_filter_keeps_matching_orders():
    node_dhl = _make_order(
        name="#1001",
        fulfillments=[FulfillmentNode(
            trackingInfo=[FulfillmentTrackingInfo(company="DHL", number="T1")]
        )],
    )
    node_fedex = _make_order(
        name="#1002",
        fulfillments=[FulfillmentNode(
            trackingInfo=[FulfillmentTrackingInfo(company="FedEx", number="T2")]
        )],
    )
    parsed = _make_parsed([node_dhl, node_fedex])

    with patch(PATCH_TARGET, return_value=parsed):
        results, warnings = lookup_order_by_tracking(
            "shop.myshopify.com", "token", "T1", carrier="DHL"
        )

    assert len(results) == 1
    assert results[0].orderNumber == "#1001"
    assert warnings == []


def test_carrier_filter_case_insensitive():
    node = _make_order(
        fulfillments=[FulfillmentNode(
            trackingInfo=[FulfillmentTrackingInfo(company="DHL", number="T1")]
        )],
    )
    parsed = _make_parsed([node])

    with patch(PATCH_TARGET, return_value=parsed):
        results, _ = lookup_order_by_tracking(
            "shop.myshopify.com", "token", "T1", carrier="dhl"
        )

    assert len(results) == 1


def test_carrier_filter_none_returns_all():
    # Two orders share the same tracking number but have different carriers.
    # carrier=None should return both.
    node1 = _make_order(name="#1001", fulfillments=[FulfillmentNode(
        trackingInfo=[FulfillmentTrackingInfo(company="DHL", number="SHARED1")]
    )])
    node2 = _make_order(name="#1002", fulfillments=[FulfillmentNode(
        trackingInfo=[FulfillmentTrackingInfo(company="FedEx", number="SHARED1")]
    )])
    parsed = _make_parsed([node1, node2])

    with patch(PATCH_TARGET, return_value=parsed):
        results, _ = lookup_order_by_tracking(
            "shop.myshopify.com", "token", "SHARED1", carrier=None
        )

    assert len(results) == 2


def test_guest_checkout_customer_name():
    node = _make_order(customer=None)  # default fulfillment has number="ABC123"
    parsed = _make_parsed([node])

    with patch(PATCH_TARGET, return_value=parsed):
        results, _ = lookup_order_by_tracking("shop.myshopify.com", "token", "ABC123")

    assert results[0].customerName == "Guest"


def test_no_shipping_line_delivery_fields_are_none():
    node = _make_order(shipping_line=None)  # default fulfillment has number="ABC123"
    parsed = _make_parsed([node])

    with patch(PATCH_TARGET, return_value=parsed):
        results, _ = lookup_order_by_tracking("shop.myshopify.com", "token", "ABC123")

    assert results[0].deliveryCost is None
    assert results[0].deliveryTitle is None


def test_has_next_page_adds_warning_when_results_match():
    node = _make_order()  # default fulfillment has number="ABC123"
    parsed = _make_parsed([node], has_next_page=True)

    with patch(PATCH_TARGET, return_value=parsed):
        _, warnings = lookup_order_by_tracking("shop.myshopify.com", "token", "ABC123")

    assert len(warnings) == 1
    assert "10" in warnings[0]


def test_has_next_page_no_warning_when_all_filtered_out():
    # hasNextPage=True but the returned orders don't actually match the
    # tracking number (Shopify fuzzy match false positives) → no warning.
    node = _make_order()  # number="ABC123"
    parsed = _make_parsed([node], has_next_page=True)

    with patch(PATCH_TARGET, return_value=parsed):
        results, warnings = lookup_order_by_tracking("shop.myshopify.com", "token", "DIFFERENT")

    assert results == []
    assert warnings == []


def test_tracking_exact_match_filters_fuzzy_results():
    # Shopify returns an order whose tracking number only partially matches —
    # the backend must discard it.
    node_exact = _make_order(name="#1001", fulfillments=[FulfillmentNode(
        trackingInfo=[FulfillmentTrackingInfo(company="DHL", number="1Z999")]
    )])
    node_fuzzy = _make_order(name="#1002", fulfillments=[FulfillmentNode(
        trackingInfo=[FulfillmentTrackingInfo(company="DHL", number="1Z999ABC")]
    )])
    parsed = _make_parsed([node_exact, node_fuzzy])

    with patch(PATCH_TARGET, return_value=parsed):
        results, _ = lookup_order_by_tracking("shop.myshopify.com", "token", "1Z999")

    assert len(results) == 1
    assert results[0].orderNumber == "#1001"


def test_graphql_send_none_returns_empty_and_warning():
    with patch(PATCH_TARGET, return_value=None):
        results, warnings = lookup_order_by_tracking("shop.myshopify.com", "token", "T1")

    assert results == []
    assert len(warnings) == 1


def test_shopify_query_uses_tracking_number_format():
    parsed = _make_parsed([])

    with patch(PATCH_TARGET, return_value=parsed) as mock_send:
        lookup_order_by_tracking("shop.myshopify.com", "token", "MYTRACK123")

    _, kwargs = mock_send.call_args
    # variables may be passed as positional arg (4th) or keyword
    call_args = mock_send.call_args
    variables = call_args[0][3] if len(call_args[0]) >= 4 else call_args[1].get("variables_dict") or call_args[0][3]
    assert variables == {"query": "tracking_number:MYTRACK123"}


def test_address_mapped_correctly():
    node = _make_order(
        shipping_address=MailingAddress(
            address1="Unter den Linden 1",
            address2="Apt 4",
            city="Berlin",
            province="Berlin",
            country="Germany",
            zip="10117",
            countryCodeV2="DE",
        )
    )  # default fulfillment has number="ABC123"
    parsed = _make_parsed([node])

    with patch(PATCH_TARGET, return_value=parsed):
        results, _ = lookup_order_by_tracking("shop.myshopify.com", "token", "ABC123")

    addr = results[0].address
    assert addr is not None
    assert addr.city == "Berlin"
    assert addr.countryCode == "DE"
    assert addr.address1 == "Unter den Linden 1"
    assert addr.address2 == "Apt 4"
    assert addr.zip == "10117"
