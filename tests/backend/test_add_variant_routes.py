import pytest
from unittest.mock import patch, MagicMock
from backend.main import application
from backend.pysrc.graphqldc.products import (
    AddVariantApplyStepDone,
    AddVariantCatalogStepDone,
    AddVariantPreviewRow,
)


@pytest.fixture
def client():
    application.config["TESTING"] = True
    with application.test_client() as c:
        yield c


def _auth(token="tok"):
    return {
        "backend.pysrc.security.Security.get_session_token": "t",
        "backend.pysrc.security.Security.get_shop_domain": "shop.myshopify.com",
        "backend.pysrc.database.Database.MutationAllow.get_allow": False,
        "backend.pysrc.database.Database.AccessTokens.get_token": token,
    }


def patches(d):
    from contextlib import ExitStack
    stack = ExitStack()
    for path, retval in d.items():
        stack.enter_context(patch(path, return_value=retval))
    return stack


# ── catalog start ─────────────────────────────────────────────────────────────

def test_catalog_start_no_token(client):
    with patches(_auth(None)):
        resp = client.post("/api/add-variant-catalog/start", json={"pattern": r"FO-\d+"})
    assert resp.status_code == 401


def test_catalog_start_missing_pattern(client):
    with patches(_auth()):
        resp = client.post("/api/add-variant-catalog/start", json={})
    assert resp.status_code == 400


def test_catalog_start_creates_job(client):
    with patches(_auth()):
        with patch("backend.main.create_add_variant_catalog_job", return_value="job-1") as mock_c:
            resp = client.post("/api/add-variant-catalog/start", json={"pattern": r"FO-\d+"})
    assert resp.status_code == 200
    assert resp.get_json()["jobId"] == "job-1"
    mock_c.assert_called_once_with("shop.myshopify.com", "tok", r"FO-\d+")


# ── catalog step ──────────────────────────────────────────────────────────────

def test_catalog_step_missing_job_id(client):
    with patches(_auth()):
        resp = client.post("/api/add-variant-catalog/step", json={})
    assert resp.status_code == 400


def test_catalog_step_unknown_job(client):
    with patches(_auth()):
        with patch("backend.main.take_add_variant_catalog_job", return_value=None):
            resp = client.post("/api/add-variant-catalog/step", json={"jobId": "x"})
    assert resp.status_code == 404


def test_catalog_step_done_deletes_job(client):
    done = AddVariantCatalogStepDone(completed=1, total=1, pattern=r"FO-\d+", productCount=3)
    mock_job = MagicMock()
    mock_job.step.return_value = done
    with patches(_auth()):
        with patch("backend.main.take_add_variant_catalog_job", return_value=mock_job), \
             patch("backend.main.delete_add_variant_catalog_job") as mock_del:
            resp = client.post("/api/add-variant-catalog/step", json={"jobId": "job-1"})
    assert resp.status_code == 200
    assert resp.get_json()["productCount"] == 3
    mock_del.assert_called_once_with("job-1")


# ── preview ───────────────────────────────────────────────────────────────────

def test_preview_missing_suffix(client):
    with patches(_auth()):
        resp = client.get("/api/add-variant/preview?pattern=FO&optionValue=1kg&weight=1000&price=9.99")
    assert resp.status_code == 400


def test_preview_invalid_weight(client):
    with patches(_auth()):
        resp = client.get(
            "/api/add-variant/preview?pattern=FO&suffix=100&optionValue=1kg&weight=abc&price=9.99"
        )
    assert resp.status_code == 400


def test_preview_zero_price(client):
    with patches(_auth()):
        resp = client.get(
            "/api/add-variant/preview?pattern=FO&suffix=100&optionValue=1kg&weight=1000&price=0"
        )
    assert resp.status_code == 400


def test_preview_conflict_returns_409(client):
    with patches(_auth()):
        with patch("backend.main.preview_add_variant", side_effect=ValueError("1 product already has")):
            resp = client.get(
                "/api/add-variant/preview?pattern=FO&suffix=100&optionValue=1kg&weight=1000&price=9.99"
            )
    assert resp.status_code == 409
    assert "already" in resp.get_json()["error"]


def test_preview_catalog_not_loaded_returns_400(client):
    with patches(_auth()):
        with patch("backend.main.preview_add_variant", side_effect=RuntimeError("not loaded")):
            resp = client.get(
                "/api/add-variant/preview?pattern=FO&suffix=100&optionValue=1kg&weight=1000&price=9.99"
            )
    assert resp.status_code == 400


def test_preview_returns_rows(client):
    row = AddVariantPreviewRow(
        productId="p1", productTitle="FO-101",
        newSku="FO-101-100", optionValue="1kg",
        weightGrams=1000.0, price="29.99",
    )
    with patches(_auth()):
        with patch("backend.main.preview_add_variant", return_value=([row], [])):
            resp = client.get(
                "/api/add-variant/preview?pattern=FO&suffix=100&optionValue=1kg&weight=1000&price=29.99"
            )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["rows"][0]["newSku"] == "FO-101-100"
    assert data["warnings"] == []


# ── apply start ───────────────────────────────────────────────────────────────

def test_set_start_missing_pattern(client):
    with patches(_auth()):
        resp = client.post("/api/add-variant/set/start", json={
            "suffix": "100", "optionValue": "1kg", "weight": 1000, "price": "9.99",
        })
    assert resp.status_code == 400


def test_set_start_missing_suffix(client):
    with patches(_auth()):
        resp = client.post("/api/add-variant/set/start", json={
            "pattern": r"FO-\d+", "optionValue": "1kg", "weight": 1000, "price": "9.99",
        })
    assert resp.status_code == 400


def test_set_start_negative_weight(client):
    with patches(_auth()):
        resp = client.post("/api/add-variant/set/start", json={
            "pattern": r"FO-\d+", "suffix": "100", "optionValue": "1kg",
            "weight": -1, "price": "9.99",
        })
    assert resp.status_code == 400


def test_set_start_creates_job(client):
    with patches(_auth()):
        with patch("backend.main.create_add_variant_apply_job", return_value="apply-1") as mock_c:
            resp = client.post("/api/add-variant/set/start", json={
                "pattern": r"FO-\d+", "suffix": "100",
                "optionValue": "1kg", "weight": 1000, "price": "29.99",
            })
    assert resp.status_code == 200
    assert resp.get_json()["jobId"] == "apply-1"
    mock_c.assert_called_once_with(
        "shop.myshopify.com", "tok", r"FO-\d+", "100", "1kg", 1000.0, "29.99"
    )


# ── apply step ────────────────────────────────────────────────────────────────

def test_set_step_unknown_job(client):
    with patches(_auth()):
        with patch("backend.main.take_add_variant_apply_job", return_value=None):
            resp = client.post("/api/add-variant/set/step", json={"jobId": "x"})
    assert resp.status_code == 404


def test_set_step_done_deletes_job(client):
    done = AddVariantApplyStepDone(completed=2, total=2, updated=2)
    mock_job = MagicMock()
    mock_job.step.return_value = done
    with patches(_auth()):
        with patch("backend.main.take_add_variant_apply_job", return_value=mock_job), \
             patch("backend.main.delete_add_variant_apply_job") as mock_del:
            resp = client.post("/api/add-variant/set/step", json={"jobId": "apply-1"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["done"] is True
    assert data["updated"] == 2
    mock_del.assert_called_once_with("apply-1")
