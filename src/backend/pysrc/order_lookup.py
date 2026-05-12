from __future__ import annotations

from .fileloader import FileLoader
from .graphql import GraphQL
from .graphqldc.orders import (
    OrderNode,
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
    date_from: str | None = None,
    date_to: str | None = None,
    max_orders: int = 250,
) -> tuple[list[OrderResult], list[str]]:
    """
    Scans orders in the given date range and returns those whose fulfillment
    tracking numbers exactly match ``tracking_number`` (case-insensitive).

    ``tracking_number`` is NOT a valid Shopify Admin GraphQL search predicate,
    so we cannot delegate filtering to the API — we page through orders and
    match client-side.
    """
    query_gql = FileLoader.load("order_by_tracking.gql")

    shopify_query_parts: list[str] = []
    if date_from:
        shopify_query_parts.append(f"created_at:>={date_from}")
    if date_to:
        shopify_query_parts.append(f"created_at:<={date_to}")
    shopify_query = " ".join(shopify_query_parts) if shopify_query_parts else None

    tracking_lower = tracking_number.lower()
    carrier_lower = carrier.lower() if carrier else None

    warnings: list[str] = []
    results: list[OrderResult] = []
    after: str | None = None
    scanned = 0

    while True:
        batch = min(250, max_orders - scanned)
        if batch <= 0:
            break

        parsed = GraphQL.send(
            shop_domain,
            token,
            query_gql,
            {"first": batch, "after": after, "query": shopify_query},
            expected_type=OrdersByTrackingData,
        )

        if parsed is None:
            warnings.append("Could not parse order response.")
            break

        conn = parsed.orders
        scanned += len(conn.edges)

        for edge in conn.edges:
            node = edge.node
            if not any(
                ti.number and ti.number.lower() == tracking_lower
                for f in node.fulfillments
                for ti in f.trackingInfo
            ):
                continue
            if carrier_lower and not any(
                ti.company and ti.company.lower() == carrier_lower
                for f in node.fulfillments
                for ti in f.trackingInfo
            ):
                continue
            results.append(_node_to_result(node))

        nxt = conn.pageInfo.next_page_cursor()

        # Stop as soon as we find the order — tracking numbers are unique per
        # shipment, so further pages won't add useful results.  Warn if there
        # are more pages just in case (e.g. split shipments, reused numbers).
        if results:
            if conn.pageInfo.hasNextPage:
                warnings.append(
                    "There may be additional orders with this tracking number."
                )
            break

        if nxt is None or scanned >= max_orders:
            break
        after = nxt

    return results, warnings


def _node_to_result(node: OrderNode) -> OrderResult:
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

    return OrderResult(
        orderNumber=node.name,
        status=node.displayFulfillmentStatus,
        customerName=customer_name,
        address=address,
        weightGrams=node.totalWeight,
        deliveryCost=delivery_cost,
        deliveryTitle=delivery_title,
        orderTotal=order_total,
    )
