import pytest
from unittest.mock import patch
from backend.pysrc.add_variant_job import (
    AddVariantCatalogJob,
    create_add_variant_catalog_job,
    take_add_variant_catalog_job,
    delete_add_variant_catalog_job,
)
from backend.pysrc.graphqldc.products import (
    AddVariantCatalogStepDone,
    AddVariantCatalogStepPending,
    AddVariantProductNode,
    AddVariantVariantNode,
    ProductOptionNode,
    ProductsAddVariantQueryData,
)
from backend.pysrc.graphqldc.common import Connection, Edge, PageInfo


def _make_product(pid, title, option_name, skus, has_next=False):
    edges = [Edge(node=AddVariantVariantNode(id=f"vid-{s}", sku=s)) for s in skus]
    return Edge(
        node=AddVariantProductNode(
            id=pid,
            title=title,
            options=[ProductOptionNode(name=option_name)],
            variants=Connection(
                edges=edges,
                pageInfo=PageInfo(hasNextPage=has_next, endCursor=None),
            ),
        )
    )


def _data(product_edges, has_next=False, cursor=None):
    return ProductsAddVariantQueryData(
        products=Connection(
            edges=product_edges,
            pageInfo=PageInfo(hasNextPage=has_next, endCursor=cursor),
        )
    )


@pytest.fixture
def job():
    return AddVariantCatalogJob(
        id="test-id",
        shop_domain="shop.myshopify.com",
        token="tok",
        pattern=r"FO-\d{3}-\d{3}",
    )


def test_step_collects_matched_products(job):
    data = _data([
        _make_product("pid1", "Product FO-101", "Size", ["FO-101-001", "FO-101-005"]),
        _make_product("pid2", "Product FO-102", "Size", ["FO-102-001", "FO-102-005"]),
    ])
    with patch("backend.pysrc.add_variant_job.GraphQL.send", return_value=data):
        result = job.step()
    assert isinstance(result, AddVariantCatalogStepDone)
    assert result.productCount == 2
    assert job.rows[0].baseSkuPrefix == "FO-101"
    assert job.rows[1].baseSkuPrefix == "FO-102"


def test_step_derives_prefix_from_first_matching_sku(job):
    data = _data([_make_product("p1", "P1", "Size", ["FO-101-001", "FO-101-005"])])
    with patch("backend.pysrc.add_variant_job.GraphQL.send", return_value=data):
        job.step()
    assert job.rows[0].baseSkuPrefix == "FO-101"


def test_step_skips_products_without_matching_sku(job):
    data = _data([_make_product("p1", "Widget", "Type", ["WIDGET-001"])])
    with patch("backend.pysrc.add_variant_job.GraphQL.send", return_value=data):
        result = job.step()
    assert isinstance(result, AddVariantCatalogStepDone)
    assert result.productCount == 0


def test_step_stores_all_variant_skus_including_non_matching(job):
    data = _data([_make_product("p1", "P1", "Size", ["FO-101-001", "UNRELATED-SKU"])])
    with patch("backend.pysrc.add_variant_job.GraphQL.send", return_value=data):
        job.step()
    assert "UNRELATED-SKU" in job.rows[0].allVariantSkus
    assert "FO-101-001" in job.rows[0].allVariantSkus


def test_step_uses_first_option_name(job):
    data = _data([_make_product("p1", "P1", "Gewicht", ["FO-101-001"])])
    with patch("backend.pysrc.add_variant_job.GraphQL.send", return_value=data):
        job.step()
    assert job.rows[0].firstOptionName == "Gewicht"


def test_step_defaults_option_name_when_no_options():
    j = AddVariantCatalogJob(id="x", shop_domain="s", token="t", pattern=r"FO-\d+")
    prod = Edge(node=AddVariantProductNode(
        id="p1", title="P1", options=[],
        variants=Connection(
            edges=[Edge(node=AddVariantVariantNode(id="v1", sku="FO-101"))],
            pageInfo=PageInfo(hasNextPage=False, endCursor=None),
        ),
    ))
    data = _data([prod])
    with patch("backend.pysrc.add_variant_job.GraphQL.send", return_value=data):
        j.step()
    assert j.rows[0].firstOptionName == "Title"


def test_invalid_pattern_exhausts_without_calling_graphql():
    j = AddVariantCatalogJob(id="x", shop_domain="s", token="t", pattern="[invalid")
    with patch("backend.pysrc.add_variant_job.GraphQL.send") as mock_send:
        result = j.step()
    mock_send.assert_not_called()
    assert isinstance(result, AddVariantCatalogStepDone)
    assert result.productCount == 0
    assert any("Invalid" in w for w in result.warnings)


def test_pagination_continues_while_has_next_page(job):
    page1 = _data(
        [_make_product("p1", "P1", "Size", ["FO-101-001"])],
        has_next=True, cursor="cur1",
    )
    page2 = _data([_make_product("p2", "P2", "Size", ["FO-102-001"])])
    with patch("backend.pysrc.add_variant_job.GraphQL.send", side_effect=[page1, page2]):
        r1 = job.step()
        assert isinstance(r1, AddVariantCatalogStepPending)
        r2 = job.step()
        assert isinstance(r2, AddVariantCatalogStepDone)
    assert r2.productCount == 2


def test_create_take_delete():
    jid = create_add_variant_catalog_job("shop.myshopify.com", "tok", r"FO-\d+")
    j = take_add_variant_catalog_job(jid)
    assert j is not None
    assert j.pattern == r"FO-\d+"
    delete_add_variant_catalog_job(jid)
    assert take_add_variant_catalog_job(jid) is None


from backend.pysrc.add_variant_preview import preview_add_variant
from backend.pysrc.graphqldc.products import AddVariantCatalogRow


def _row(pid, ptitle, prefix, all_skus, option_name="Size"):
    return AddVariantCatalogRow(
        productId=pid,
        productTitle=ptitle,
        firstOptionName=option_name,
        baseSkuPrefix=prefix,
        allVariantSkus=all_skus,
    )


def test_preview_returns_rows_with_computed_sku():
    rows = [
        _row("p1", "Product FO-101", "FO-101", ["FO-101-001", "FO-101-005"]),
        _row("p2", "Product FO-102", "FO-102", ["FO-102-001"]),
    ]
    with patch("backend.pysrc.add_variant_preview.get_add_variant_catalog", return_value=(rows, [])):
        result, warnings = preview_add_variant("shop", r"FO-\d+", "100", "1kg", 1000.0, "29.99")
    assert len(result) == 2
    skus = {r.newSku for r in result}
    assert "FO-101-100" in skus
    assert "FO-102-100" in skus
    assert warnings == []


def test_preview_raises_value_error_on_conflict():
    rows = [_row("p1", "FO-101", "FO-101", ["FO-101-001", "FO-101-100"])]
    with patch("backend.pysrc.add_variant_preview.get_add_variant_catalog", return_value=(rows, [])):
        with pytest.raises(ValueError, match="already"):
            preview_add_variant("shop", r"FO-\d+", "100", "1kg", 1000.0, "29.99")


def test_preview_raises_runtime_error_when_catalog_not_loaded():
    with patch("backend.pysrc.add_variant_preview.get_add_variant_catalog", return_value=None):
        with pytest.raises(RuntimeError):
            preview_add_variant("shop", r"FO-\d+", "100", "1kg", 1000.0, "29.99")


def test_preview_sorted_by_product_title():
    rows = [
        _row("p1", "Zeta product", "ZP-001", ["ZP-001-001"]),
        _row("p2", "Alpha product", "AP-001", ["AP-001-001"]),
    ]
    with patch("backend.pysrc.add_variant_preview.get_add_variant_catalog", return_value=(rows, [])):
        result, _ = preview_add_variant("shop", r"\w+-\d+-\d+", "100", "1kg", 500.0, "9.99")
    assert result[0].productTitle == "Alpha product"
    assert result[1].productTitle == "Zeta product"
