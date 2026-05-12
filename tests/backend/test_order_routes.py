import pytest
from unittest.mock import patch, MagicMock
from backend.main import application
from backend.pysrc.graphqldc.orders import OrderCarrierStepDone, OrderCarrierStepPending, OrderResult


@pytest.fixture
def client():
    application.config["TESTING"] = True
    with application.test_client() as c:
        yield c


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


def test_order_lookup_passes_date_range_and_carrier(client):
    with patch("backend.pysrc.security.Security.get_session_token", return_value="t"), \
         patch("backend.pysrc.security.Security.get_shop_domain", return_value="shop.myshopify.com"), \
         patch("backend.pysrc.database.Database.MutationAllow.get_allow", return_value=False), \
         patch("backend.pysrc.database.Database.AccessTokens.get_token", return_value="tok"), \
         patch("backend.main.lookup_order_by_tracking", return_value=([], [])) as mock_lookup:
        client.get(
            "/api/order-by-tracking"
            "?trackingNumber=X&carrier=DHL&dateFrom=2024-01-01&dateTo=2024-12-31&maxOrders=500"
        )
    mock_lookup.assert_called_once_with(
        "shop.myshopify.com", "tok", "X", "DHL",
        date_from="2024-01-01", date_to="2024-12-31", max_orders=500,
    )
