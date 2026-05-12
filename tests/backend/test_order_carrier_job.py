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
        max_orders=1000,
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
