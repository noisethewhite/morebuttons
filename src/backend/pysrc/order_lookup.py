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
