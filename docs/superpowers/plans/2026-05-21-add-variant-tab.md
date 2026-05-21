# Add Variant Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fifth "Add variant" tab that finds products by variant SKU regex and bulk-creates one new variant per matched product, with per-product SKU construction and an explicit preview step.

**Architecture:** Follows the exact SkuWeightPanel pattern — stepped catalog scan job → cache → explicit preview endpoint → stepped apply job. The new variant's SKU is constructed per product as `{basePrefix}-{userSuffix}` where the prefix is derived by stripping the last `-segment` from a matching variant SKU. Preview only refreshes on explicit button press (no auto-update on field change).

**Tech Stack:** Python/Flask backend with Pydantic dataclasses, Shopify Admin GraphQL API (`productVariantsBulkCreate`), React/TypeScript frontend matching existing `SkuWeightPanel` UI patterns, pytest for backend tests.

---

## File Map

**Create:**
- `src/backend/graphql/products_add_variant_page.gql` — paginated product query with options + all variant SKUs
- `src/backend/graphql/product_variants_bulk_create.gql` — create-variant mutation
- `src/backend/pysrc/add_variant_job.py` — catalog scan job
- `src/backend/pysrc/add_variant_preview.py` — preview logic (conflict check)
- `src/backend/pysrc/add_variant_apply_job.py` — stepped apply job
- `src/frontend/tsxsrc/AddVariantPanel.tsx` — tab panel component
- `tests/backend/test_add_variant_job.py` — unit tests for catalog job
- `tests/backend/test_add_variant_routes.py` — route handler tests

**Modify:**
- `src/backend/pysrc/graphqldc/products.py` — new dataclasses for GQL types, app rows, step results
- `src/backend/pysrc/catalog_cache.py` — new `_add_variant_catalog` dict + get/set/invalidate
- `src/backend/pysrc/routes.py` — 5 new route constants
- `src/backend/main.py` — 5 new route handlers + imports
- `src/frontend/tsxsrc/app.tsx` — new tab button + panel

---

### Task 1: GraphQL files

**Files:**
- Create: `src/backend/graphql/products_add_variant_page.gql`
- Create: `src/backend/graphql/product_variants_bulk_create.gql`

- [ ] **Step 1: Write `products_add_variant_page.gql`**

```graphql
query ProductsAddVariantPage($first: Int!, $after: String) {
  products(first: $first, after: $after) {
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        id
        title
        options {
          name
        }
        variants(first: 100) {
          pageInfo {
            hasNextPage
          }
          edges {
            node {
              id
              sku
            }
          }
        }
      }
    }
  }
}
```

- [ ] **Step 2: Write `product_variants_bulk_create.gql`**

```graphql
mutation ProductVariantsBulkCreate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkCreate(productId: $productId, variants: $variants) {
    productVariants {
      id
    }
    userErrors {
      field
      message
    }
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add src/backend/graphql/products_add_variant_page.gql src/backend/graphql/product_variants_bulk_create.gql
git commit -m "feat: add GQL files for add-variant feature"
```

---

### Task 2: Dataclasses in `graphqldc/products.py`

**Files:**
- Modify: `src/backend/pysrc/graphqldc/products.py`

- [ ] **Step 1: Append new dataclasses at the end of the file**

Open `src/backend/pysrc/graphqldc/products.py` and append the following block after the last existing definition:

```python
# --- products_add_variant_page.gql ---


@dataclass(config=_CONFIG)
class ProductOptionNode:
    name: str


@dataclass(config=_CONFIG)
class AddVariantVariantNode:
    id: str
    sku: str | None = None


@dataclass(config=_CONFIG)
class AddVariantProductNode:
    id: str
    title: str | None = None
    options: list[ProductOptionNode] = field(default_factory=list)
    variants: Connection[AddVariantVariantNode] | None = None


@dataclass(config=_CONFIG)
class ProductsAddVariantQueryData:
    products: Connection[AddVariantProductNode]


# --- add_variant app-level rows ---


@dataclass(config=_CONFIG)
class AddVariantCatalogRow:
    productId: str
    productTitle: str
    firstOptionName: str
    baseSkuPrefix: str
    allVariantSkus: list[str]


@dataclass(config=_CONFIG)
class AddVariantPreviewRow(Jsonable):
    productId: str
    productTitle: str
    newSku: str
    optionValue: str
    weightGrams: float
    price: str


# --- product_variants_bulk_create.gql input types ---


@dataclass(config=_CONFIG)
class VariantOptionValueInput:
    optionName: str
    name: str


@dataclass(config=_CONFIG)
class VariantBulkCreateInputRow:
    price: str
    sku: str
    optionValues: list[VariantOptionValueInput]
    inventoryItem: InventoryItemWeightInput


@dataclass(config=_CONFIG)
class VariantBulkCreateVariables(Jsonable):
    productId: str
    variants: list[VariantBulkCreateInputRow]


# --- product_variants_bulk_create.gql response ---


@dataclass(config=_CONFIG)
class ProductVariantsBulkCreatePayload:
    productVariants: list[ProductVariantSnippet] | None = None
    userErrors: list[UserError] | None = None

    def user_error_messages(self) -> list[str]:
        return [ue.message for ue in (self.userErrors or []) if ue.message]

    def mutation_succeeded(self) -> bool:
        return not self.userErrors


@dataclass(config=_CONFIG)
class ProductVariantsBulkCreateData:
    productVariantsBulkCreate: ProductVariantsBulkCreatePayload | None = None


# --- add_variant catalog job step results ---


@dataclass(config=_CONFIG)
class AddVariantCatalogStepPending(Jsonable):
    completed: int
    remaining: int
    total: int
    done: Literal[False] = False
    phase: Literal["add_variant"] = "add_variant"


@dataclass(config=_CONFIG)
class AddVariantCatalogStepDone(Jsonable):
    completed: int
    total: int
    pattern: str
    productCount: int
    warnings: list[str] = field(default_factory=list)
    done: Literal[True] = True
    remaining: int = 0
    phase: Literal["add_variant"] = "add_variant"


AddVariantCatalogStepResult = AddVariantCatalogStepPending | AddVariantCatalogStepDone


@dataclass(config=_CONFIG)
class AddVariantApplyStepPending(Jsonable):
    completed: int
    remaining: int
    total: int
    done: Literal[False] = False
    phase: Literal["add_variant_apply"] = "add_variant_apply"


@dataclass(config=_CONFIG)
class AddVariantApplyStepDone(Jsonable):
    completed: int
    total: int
    updated: int
    warnings: list[str] = field(default_factory=list)
    userErrors: list[str] = field(default_factory=list)
    done: Literal[True] = True
    remaining: int = 0
    phase: Literal["add_variant_apply"] = "add_variant_apply"


AddVariantApplyStepResult = AddVariantApplyStepPending | AddVariantApplyStepDone
```

- [ ] **Step 2: Commit**

```bash
git add src/backend/pysrc/graphqldc/products.py
git commit -m "feat: add dataclasses for add-variant feature"
```

---

### Task 3: Cache additions

**Files:**
- Modify: `src/backend/pysrc/catalog_cache.py`

- [ ] **Step 1: Add import at top of file**

The file already imports `SkuWeightVariantRow` and `TaggedVariantRow`. Add `AddVariantCatalogRow` to that import:

```python
from .graphqldc.products import AddVariantCatalogRow, SkuWeightVariantRow, TaggedVariantRow
```

- [ ] **Step 2: Append cache dict and functions at end of file**

```python
_add_variant_catalog: dict[str, tuple[list[AddVariantCatalogRow], list[str]]] = {}


def _av_key(shop_domain: str, pattern: str) -> str:
    return f"{shop_domain}\n{pattern.strip()}"


def get_add_variant_catalog(
    shop_domain: str, pattern: str
) -> tuple[list[AddVariantCatalogRow], list[str]] | None:
    return _add_variant_catalog.get(_av_key(shop_domain, pattern))


def set_add_variant_catalog(
    shop_domain: str,
    pattern: str,
    rows: list[AddVariantCatalogRow],
    warnings: list[str],
) -> None:
    _add_variant_catalog[_av_key(shop_domain, pattern)] = (rows, list(warnings))


def invalidate_add_variant_catalog(shop_domain: str, pattern: str) -> None:
    _ = _add_variant_catalog.pop(_av_key(shop_domain, pattern), None)
```

- [ ] **Step 3: Commit**

```bash
git add src/backend/pysrc/catalog_cache.py
git commit -m "feat: add cache slot for add-variant catalog"
```

---

### Task 4: Route constants

**Files:**
- Modify: `src/backend/pysrc/routes.py`

- [ ] **Step 1: Append 5 new route constants at end of `Routes` class**

```python
    ADD_VARIANT_CATALOG_START = f"{API}/add-variant-catalog/start"
    ADD_VARIANT_CATALOG_STEP  = f"{API}/add-variant-catalog/step"
    ADD_VARIANT_PREVIEW       = f"{API}/add-variant/preview"
    ADD_VARIANT_SET_START     = f"{API}/add-variant/set/start"
    ADD_VARIANT_SET_STEP      = f"{API}/add-variant/set/step"
```

- [ ] **Step 2: Commit**

```bash
git add src/backend/pysrc/routes.py
git commit -m "feat: add route constants for add-variant endpoints"
```

---

### Task 5: Catalog scan job with tests

**Files:**
- Create: `src/backend/pysrc/add_variant_job.py`
- Create: `tests/backend/test_add_variant_job.py`

- [ ] **Step 1: Write failing tests**

Create `tests/backend/test_add_variant_job.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect ImportError (module not yet created)**

```bash
cd /Users/user/Dev/morebuttons && .venv/bin/pytest tests/backend/test_add_variant_job.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError` or `ImportError` for `add_variant_job`.

- [ ] **Step 3: Create `src/backend/pysrc/add_variant_job.py`**

```python
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from .catalog_cache import set_add_variant_catalog
from .fileloader import FileLoader
from .graphql import GraphQL
from .graphqldc.products import (
    AddVariantCatalogRow,
    AddVariantCatalogStepDone,
    AddVariantCatalogStepPending,
    AddVariantCatalogStepResult,
    ProductsAddVariantQueryData,
)


@dataclass
class AddVariantCatalogJob:
    id: str
    shop_domain: str
    token: str
    pattern: str
    rows: list[AddVariantCatalogRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    after: str | None = None
    exhausted: bool = False
    completed_steps: int = 0
    _compiled: re.Pattern | None = field(init=False)
    _query: str = field(init=False)

    def __post_init__(self) -> None:
        self._query = FileLoader.load("products_add_variant_page.gql")
        try:
            self._compiled = re.compile(self.pattern, re.IGNORECASE)
        except re.error as e:
            self._compiled = None
            self.warnings.append(f"Invalid regex pattern: {e}")
            self.exhausted = True

    def step(self) -> AddVariantCatalogStepResult:
        self.completed_steps += 1
        if self.exhausted:
            return self._finish()
        return self._step_products()

    def _step_products(self) -> AddVariantCatalogStepResult:
        compiled = self._compiled
        if compiled is None:
            self.exhausted = True
            return self._finish()

        try:
            parsed = GraphQL.send(
                self.shop_domain,
                self.token,
                self._query,
                {"first": 50, "after": self.after},
                expected_type=ProductsAddVariantQueryData,
            )
        except RuntimeError as e:
            self.warnings.append(str(e))
            self.exhausted = True
            return self._finish()

        if parsed is None:
            self.warnings.append("Unexpected response from products query.")
            self.exhausted = True
            return self._finish()

        for edge in parsed.products.edges:
            prod = edge.node
            pid = prod.id
            ptitle = prod.title or ""
            first_option_name = prod.options[0].name if prod.options else "Title"

            if not prod.variants:
                continue
            if prod.variants.pageInfo.hasNextPage is True:
                self.warnings.append(
                    f'Product "{ptitle}" has more than 100 variants; '
                    "only the first page was loaded."
                )

            all_skus: list[str] = []
            matching_skus: list[str] = []
            for ve in prod.variants.edges:
                sku = (ve.node.sku or "").strip()
                if sku:
                    all_skus.append(sku)
                    if compiled.search(sku):
                        matching_skus.append(sku)

            if not matching_skus:
                continue

            base_prefix = matching_skus[0].rsplit("-", 1)[0]
            self.rows.append(AddVariantCatalogRow(
                productId=pid,
                productTitle=ptitle,
                firstOptionName=first_option_name,
                baseSkuPrefix=base_prefix,
                allVariantSkus=all_skus,
            ))

        nxt = parsed.products.pageInfo.next_page_cursor()
        if nxt is None:
            self.exhausted = True
        else:
            self.after = nxt

        if self.exhausted:
            return self._finish()
        return AddVariantCatalogStepPending(
            completed=self.completed_steps,
            remaining=1,
            total=self.completed_steps + 1,
        )

    def _finish(self) -> AddVariantCatalogStepDone:
        set_add_variant_catalog(self.shop_domain, self.pattern, self.rows, self.warnings)
        return AddVariantCatalogStepDone(
            completed=self.completed_steps,
            total=self.completed_steps,
            pattern=self.pattern,
            productCount=len(self.rows),
            warnings=list(self.warnings),
        )


_JOBS: dict[str, AddVariantCatalogJob] = {}


def create_add_variant_catalog_job(shop_domain: str, token: str, pattern: str) -> str:
    jid = uuid.uuid4().hex
    _JOBS[jid] = AddVariantCatalogJob(
        id=jid, shop_domain=shop_domain, token=token, pattern=pattern
    )
    return jid


def take_add_variant_catalog_job(job_id: str) -> AddVariantCatalogJob | None:
    return _JOBS.get(job_id)


def delete_add_variant_catalog_job(job_id: str) -> None:
    _ = _JOBS.pop(job_id, None)
```

- [ ] **Step 4: Run tests — all should pass**

```bash
cd /Users/user/Dev/morebuttons && .venv/bin/pytest tests/backend/test_add_variant_job.py -v
```

Expected: all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/backend/pysrc/add_variant_job.py tests/backend/test_add_variant_job.py
git commit -m "feat: add variant catalog scan job with tests"
```

---

### Task 6: Preview function with tests

**Files:**
- Create: `src/backend/pysrc/add_variant_preview.py`

- [ ] **Step 1: Write failing tests — append to `tests/backend/test_add_variant_job.py`**

Add these tests at the end of `tests/backend/test_add_variant_job.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
cd /Users/user/Dev/morebuttons && .venv/bin/pytest tests/backend/test_add_variant_job.py -v -k "preview" 2>&1 | head -10
```

- [ ] **Step 3: Create `src/backend/pysrc/add_variant_preview.py`**

```python
from __future__ import annotations

from .catalog_cache import get_add_variant_catalog
from .graphqldc.products import AddVariantPreviewRow


def preview_add_variant(
    shop_domain: str,
    pattern: str,
    suffix: str,
    option_value: str,
    weight_g: float,
    price: str,
) -> tuple[list[AddVariantPreviewRow], list[str]]:
    cached = get_add_variant_catalog(shop_domain, pattern)
    if cached is None:
        raise RuntimeError(
            "Add variant catalog for this pattern is not loaded. "
            "Wait for loading to finish."
        )
    rows, warnings = cached

    conflicts: list[str] = []
    for row in rows:
        new_sku = f"{row.baseSkuPrefix}-{suffix}"
        if new_sku in row.allVariantSkus:
            conflicts.append(f"{row.productTitle} ({new_sku})")

    if conflicts:
        n = len(conflicts)
        noun = "product" if n == 1 else "products"
        verb = "has" if n == 1 else "have"
        sample = ", ".join(conflicts[:5]) + ("…" if len(conflicts) > 5 else "")
        raise ValueError(
            f"{n} {noun} already {verb} a variant with the target SKU: {sample}"
        )

    preview_rows = sorted(
        [
            AddVariantPreviewRow(
                productId=row.productId,
                productTitle=row.productTitle,
                newSku=f"{row.baseSkuPrefix}-{suffix}",
                optionValue=option_value,
                weightGrams=weight_g,
                price=price,
            )
            for row in rows
        ],
        key=lambda r: r.productTitle.lower(),
    )
    return preview_rows, list(warnings)
```

- [ ] **Step 4: Run all preview tests**

```bash
cd /Users/user/Dev/morebuttons && .venv/bin/pytest tests/backend/test_add_variant_job.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/backend/pysrc/add_variant_preview.py tests/backend/test_add_variant_job.py
git commit -m "feat: add variant preview function with tests"
```

---

### Task 7: Apply job

**Files:**
- Create: `src/backend/pysrc/add_variant_apply_job.py`

- [ ] **Step 1: Create `src/backend/pysrc/add_variant_apply_job.py`**

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .catalog_cache import get_add_variant_catalog, invalidate_add_variant_catalog
from .fileloader import FileLoader
from .graphql import GraphQL
from .graphqldc.products import (
    AddVariantApplyStepDone,
    AddVariantApplyStepPending,
    AddVariantApplyStepResult,
    InventoryItemMeasurementInput,
    InventoryItemWeightInput,
    ProductVariantsBulkCreateData,
    VariantBulkCreateInputRow,
    VariantBulkCreateVariables,
    VariantOptionValueInput,
    WeightInput,
)


@dataclass
class AddVariantApplyJob:
    id: str
    shop_domain: str
    token: str
    option_value: str
    weight_g: float
    price: str
    # (productId, firstOptionName, newSku)
    tasks: list[tuple[str, str, str]]
    warnings: list[str] = field(default_factory=list)
    user_msgs: list[str] = field(default_factory=list)
    completed: int = 0
    updated: int = 0
    _mut: str = field(init=False)

    def __post_init__(self) -> None:
        self._mut = FileLoader.load("product_variants_bulk_create.gql")

    def step(self) -> AddVariantApplyStepResult:
        if not self.tasks:
            return self._finish()

        product_id, option_name, new_sku = self.tasks.pop(0)
        variant = VariantBulkCreateInputRow(
            price=self.price,
            sku=new_sku,
            optionValues=[VariantOptionValueInput(optionName=option_name, name=self.option_value)],
            inventoryItem=InventoryItemWeightInput(
                measurement=InventoryItemMeasurementInput(
                    weight=WeightInput(value=self.weight_g, unit="GRAMS")
                )
            ),
        )
        variables = VariantBulkCreateVariables(productId=product_id, variants=[variant])
        parsed, soft_errs = GraphQL.send(
            self.shop_domain,
            self.token,
            self._mut,
            variables.to_json(),
            expected_type=ProductVariantsBulkCreateData,
            raise_on_graphql_error=False,
        )
        self.completed += 1

        if parsed is None:
            self.user_msgs.extend(soft_errs)
        else:
            payload = parsed.productVariantsBulkCreate
            if payload is None:
                self.user_msgs.append(
                    f"Product {product_id}: missing productVariantsBulkCreate."
                )
            elif not payload.mutation_succeeded():
                self.user_msgs.extend(payload.user_error_messages())
            else:
                self.updated += 1

        if not self.tasks:
            return self._finish()

        rem = len(self.tasks)
        return AddVariantApplyStepPending(
            completed=self.completed,
            remaining=rem,
            total=self.completed + rem,
        )

    def _finish(self) -> AddVariantApplyStepDone:
        return AddVariantApplyStepDone(
            completed=self.completed,
            total=self.completed,
            updated=self.updated,
            warnings=list(self.warnings),
            userErrors=list(self.user_msgs),
        )


_APPLY_JOBS: dict[str, AddVariantApplyJob] = {}


def create_add_variant_apply_job(
    shop_domain: str,
    token: str,
    pattern: str,
    suffix: str,
    option_value: str,
    weight_g: float,
    price: str,
) -> str:
    cached = get_add_variant_catalog(shop_domain, pattern)
    if cached is None:
        raise RuntimeError("Add variant catalog for this pattern is not loaded.")
    rows, warnings = cached

    tasks = [
        (row.productId, row.firstOptionName, f"{row.baseSkuPrefix}-{suffix}")
        for row in rows
    ]
    invalidate_add_variant_catalog(shop_domain, pattern)

    jid = uuid.uuid4().hex
    _APPLY_JOBS[jid] = AddVariantApplyJob(
        id=jid,
        shop_domain=shop_domain,
        token=token,
        option_value=option_value,
        weight_g=weight_g,
        price=price,
        tasks=tasks,
        warnings=list(warnings),
    )
    return jid


def take_add_variant_apply_job(job_id: str) -> AddVariantApplyJob | None:
    return _APPLY_JOBS.get(job_id)


def delete_add_variant_apply_job(job_id: str) -> None:
    _ = _APPLY_JOBS.pop(job_id, None)
```

- [ ] **Step 2: Verify Python syntax**

```bash
cd /Users/user/Dev/morebuttons && .venv/bin/python -c "from backend.pysrc.add_variant_apply_job import create_add_variant_apply_job; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/backend/pysrc/add_variant_apply_job.py
git commit -m "feat: add variant apply job"
```

---

### Task 8: Backend route handlers with tests

**Files:**
- Modify: `src/backend/main.py`
- Create: `tests/backend/test_add_variant_routes.py`

- [ ] **Step 1: Write failing route tests**

Create `tests/backend/test_add_variant_routes.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect import failures**

```bash
cd /Users/user/Dev/morebuttons && .venv/bin/pytest tests/backend/test_add_variant_routes.py -v 2>&1 | head -15
```

- [ ] **Step 3: Add imports to `main.py`**

Add these imports after the existing `sku_weight_pricing` import line in `src/backend/main.py`:

```python
from backend.pysrc.add_variant_job import (
    create_add_variant_catalog_job,
    delete_add_variant_catalog_job,
    take_add_variant_catalog_job,
)
from backend.pysrc.add_variant_apply_job import (
    create_add_variant_apply_job,
    delete_add_variant_apply_job,
    take_add_variant_apply_job,
)
from backend.pysrc.add_variant_preview import preview_add_variant
```

- [ ] **Step 4: Append 5 route handlers to `main.py`** (before the final `index` route)

```python
@application.route(Routes.ADD_VARIANT_CATALOG_START, methods=["POST"])
def add_variant_catalog_start():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({"error": "Not installed"}), 401
    raw_body = cast(Json.Value, flask.request.get_json(silent=True))
    body = raw_body if isinstance(raw_body, dict) else {}
    pattern_raw = body.get("pattern")
    pattern = pattern_raw.strip() if isinstance(pattern_raw, str) else ""
    if not pattern:
        return flask.jsonify({"error": "Missing pattern"}), 400
    jid = create_add_variant_catalog_job(Server.shop_domain, token, pattern)
    return flask.jsonify({"jobId": jid})


@application.route(Routes.ADD_VARIANT_CATALOG_STEP, methods=["POST"])
def add_variant_catalog_step():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({"error": "Not installed"}), 401
    raw_body = cast(Json.Value, flask.request.get_json(silent=True))
    body = raw_body if isinstance(raw_body, dict) else {}
    job_id = body.get("jobId")
    if not isinstance(job_id, str) or not job_id.strip():
        return flask.jsonify({"error": "Missing jobId"}), 400
    job = take_add_variant_catalog_job(job_id.strip())
    if job is None:
        return flask.jsonify({"error": "Unknown or expired job"}), 404
    try:
        result = job.step()
    except RuntimeError as e:
        return flask.jsonify({"error": str(e)}), 502
    flask.g.graphql_phase_total = result.total
    flask.g.graphql_phase_done = result.completed
    if result.done:
        delete_add_variant_catalog_job(job_id.strip())
    return flask.jsonify(result.to_json())


@application.route(Routes.ADD_VARIANT_PREVIEW, methods=["GET"])
def add_variant_preview():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({"error": "Not installed"}), 401
    pattern = flask.request.args.get("pattern", "").strip()
    if not pattern:
        return flask.jsonify({"error": "Missing pattern"}), 400
    suffix = flask.request.args.get("suffix", "").strip()
    if not suffix:
        return flask.jsonify({"error": "Missing suffix"}), 400
    option_value = flask.request.args.get("optionValue", "").strip()
    if not option_value:
        return flask.jsonify({"error": "Missing optionValue"}), 400
    weight_raw = flask.request.args.get("weight", "").strip()
    try:
        weight_g = float(weight_raw)
    except (TypeError, ValueError):
        return flask.jsonify({"error": "Invalid weight"}), 400
    if weight_g < 0:
        return flask.jsonify({"error": "Weight must be non-negative"}), 400
    price = flask.request.args.get("price", "").strip()
    if not price:
        return flask.jsonify({"error": "Missing price"}), 400
    try:
        price_f = float(price)
    except (TypeError, ValueError):
        return flask.jsonify({"error": "Invalid price"}), 400
    if price_f <= 0:
        return flask.jsonify({"error": "Price must be greater than 0"}), 400
    try:
        rows, warnings = preview_add_variant(
            Server.shop_domain, pattern, suffix, option_value, weight_g, price
        )
        return flask.jsonify({"rows": [r.to_json() for r in rows], "warnings": warnings})
    except ValueError as e:
        return flask.jsonify({"error": str(e)}), 409
    except RuntimeError as e:
        return flask.jsonify({"error": str(e)}), 400


@application.route(Routes.ADD_VARIANT_SET_START, methods=["POST"])
def add_variant_set_start():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({"error": "Not installed"}), 401
    raw_body = cast(Json.Value, flask.request.get_json(silent=True))
    body = raw_body if isinstance(raw_body, dict) else {}
    pattern_raw = body.get("pattern")
    pattern = pattern_raw.strip() if isinstance(pattern_raw, str) else ""
    if not pattern:
        return flask.jsonify({"error": "Missing pattern"}), 400
    suffix_raw = body.get("suffix")
    suffix = suffix_raw.strip() if isinstance(suffix_raw, str) else ""
    if not suffix:
        return flask.jsonify({"error": "Missing suffix"}), 400
    option_value_raw = body.get("optionValue")
    option_value = option_value_raw.strip() if isinstance(option_value_raw, str) else ""
    if not option_value:
        return flask.jsonify({"error": "Missing optionValue"}), 400
    weight_raw = body.get("weight")
    if isinstance(weight_raw, bool) or weight_raw is None:
        return flask.jsonify({"error": "Invalid weight"}), 400
    try:
        weight_g = float(
            weight_raw if isinstance(weight_raw, (int, float)) else str(weight_raw).strip()
        )
    except (TypeError, ValueError):
        return flask.jsonify({"error": "Invalid weight"}), 400
    if weight_g < 0:
        return flask.jsonify({"error": "Weight must be non-negative"}), 400
    price_raw = body.get("price")
    price = price_raw.strip() if isinstance(price_raw, str) else ""
    if not price:
        return flask.jsonify({"error": "Missing price"}), 400
    try:
        price_f = float(price)
    except (TypeError, ValueError):
        return flask.jsonify({"error": "Invalid price"}), 400
    if price_f <= 0:
        return flask.jsonify({"error": "Price must be greater than 0"}), 400
    try:
        jid = create_add_variant_apply_job(
            Server.shop_domain, token, pattern, suffix, option_value, weight_g, price
        )
        return flask.jsonify({"jobId": jid})
    except RuntimeError as e:
        return flask.jsonify({"error": str(e)}), 400


@application.route(Routes.ADD_VARIANT_SET_STEP, methods=["POST"])
def add_variant_set_step():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({"error": "Not installed"}), 401
    raw_body = cast(Json.Value, flask.request.get_json(silent=True))
    body = raw_body if isinstance(raw_body, dict) else {}
    job_id = body.get("jobId")
    if not isinstance(job_id, str) or not job_id.strip():
        return flask.jsonify({"error": "Missing jobId"}), 400
    job = take_add_variant_apply_job(job_id.strip())
    if job is None:
        return flask.jsonify({"error": "Unknown or expired job"}), 404
    try:
        result = job.step()
    except RuntimeError as e:
        return flask.jsonify({"error": str(e)}), 502
    flask.g.graphql_phase_total = result.total
    flask.g.graphql_phase_done = result.completed
    if result.done:
        delete_add_variant_apply_job(job_id.strip())
    return flask.jsonify(result.to_json())
```

- [ ] **Step 5: Run all route tests**

```bash
cd /Users/user/Dev/morebuttons && .venv/bin/pytest tests/backend/test_add_variant_routes.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Run full test suite to check for regressions**

```bash
cd /Users/user/Dev/morebuttons && .venv/bin/pytest tests/ -v
```

Expected: all existing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add src/backend/main.py tests/backend/test_add_variant_routes.py
git commit -m "feat: add variant route handlers with tests"
```

---

### Task 9: `AddVariantPanel.tsx`

**Files:**
- Create: `src/frontend/tsxsrc/AddVariantPanel.tsx`

- [ ] **Step 1: Create `src/frontend/tsxsrc/AddVariantPanel.tsx`**

```tsx
import {
    ReactNode,
    useCallback,
    useState,
} from "react"
import type { SubmitEventHandler } from "react"
import AppBridge from "../tssrc/app_bridge"
import { runSteppedCatalogJob } from "../tssrc/catalog_job"
import StatusMessageLog, { useStatusMessageLog } from "./status_message_log"

interface AddVariantPreviewRow {
    productId: string
    productTitle: string
    newSku: string
    optionValue: string
    weightGrams: number
    price: string
}

interface PreviewResponse {
    rows: AddVariantPreviewRow[]
    warnings?: string[]
    error?: string
}

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

export default function AddVariantPanel(): ReactNode {
    const [pattern, setPattern] = useState("")
    const [optionValue, setOptionValue] = useState("")
    const [skuSuffix, setSkuSuffix] = useState("")
    const [weightGrams, setWeightGrams] = useState("")
    const [price, setPrice] = useState("")

    const [catalogLoading, setCatalogLoading] = useState(false)
    const [loadedPattern, setLoadedPattern] = useState("")
    const [productCount, setProductCount] = useState<number | null>(null)

    const [previewRows, setPreviewRows] = useState<AddVariantPreviewRow[] | null>(null)
    const [previewLoading, setPreviewLoading] = useState(false)
    const [previewError, setPreviewError] = useState<string | null>(null)
    const [previewWarnings, setPreviewWarnings] = useState<string | null>(null)

    const [pendingConfirmation, setPendingConfirmation] = useState(false)
    const [submitting, setSubmitting] = useState(false)

    const { entries: statusLog, push: pushStatus } = useStatusMessageLog()

    const loadCatalog = useCallback(async (pat: string): Promise<void> => {
        setCatalogLoading(true)
        setLoadedPattern("")
        setProductCount(null)
        setPreviewRows(null)
        setPreviewError(null)
        setPreviewWarnings(null)
        try {
            const result = await runSteppedCatalogJob(
                "/api/add-variant-catalog/start",
                "/api/add-variant-catalog/step",
                { pattern: pat },
            )
            const pc = result.productCount
            setProductCount(typeof pc === "number" ? pc : 0)
            setLoadedPattern(pat)
            const w = result.warnings
            if (Array.isArray(w) && w.length) {
                pushStatus("ok", `Loaded. Notes: ${(w as string[]).join(" ")}`)
            }
        } catch (e) {
            pushStatus("err", e instanceof Error ? e.message : "Could not load catalog.")
        } finally {
            setCatalogLoading(false)
        }
    }, [pushStatus])

    const refreshPreview = useCallback(async (): Promise<void> => {
        const trimmedPat = pattern.trim()
        const trimmedSuffix = skuSuffix.trim()
        const trimmedOv = optionValue.trim()
        const trimmedW = weightGrams.trim()
        const trimmedP = price.trim()
        if (!trimmedPat || !trimmedSuffix || !trimmedOv || !trimmedW || !trimmedP) return
        if (loadedPattern !== trimmedPat) return
        setPreviewLoading(true)
        setPreviewError(null)
        setPreviewWarnings(null)
        setPreviewRows(null)
        try {
            const q = new URLSearchParams({
                pattern: trimmedPat,
                suffix: trimmedSuffix,
                optionValue: trimmedOv,
                weight: trimmedW,
                price: trimmedP,
            })
            const res = await AppBridge.fetchWithToken(`/api/add-variant/preview?${q.toString()}`)
            const data = await readJsonBody<PreviewResponse>(res)
            if (!res.ok) {
                setPreviewError(data?.error ?? `Preview failed (${res.status}).`)
                return
            }
            if (!data) {
                setPreviewError("Preview failed: response was not JSON.")
                return
            }
            setPreviewRows(data.rows ?? [])
            setPreviewWarnings(data.warnings?.length ? data.warnings.join(" ") : null)
        } catch {
            setPreviewError("Could not load preview.")
        } finally {
            setPreviewLoading(false)
        }
    }, [pattern, skuSuffix, optionValue, weightGrams, price, loadedPattern])

    const onSubmitSet: SubmitEventHandler<HTMLFormElement> = (e) => {
        e.preventDefault()
        const trimmedPat = pattern.trim()
        if (!trimmedPat) { pushStatus("err", "Enter a SKU regex pattern."); return }
        if (catalogLoading || loadedPattern !== trimmedPat) { pushStatus("err", "Scan the catalog first."); return }
        if (!skuSuffix.trim()) { pushStatus("err", "Enter a SKU suffix."); return }
        if (!optionValue.trim()) { pushStatus("err", "Enter an option value."); return }
        const wNum = Number(weightGrams.trim())
        if (weightGrams.trim() === "" || Number.isNaN(wNum) || wNum < 0) {
            pushStatus("err", "Enter a valid weight in grams (0 or more).")
            return
        }
        const pNum = Number(price.trim())
        if (price.trim() === "" || Number.isNaN(pNum) || pNum <= 0) {
            pushStatus("err", "Enter a valid price greater than 0.")
            return
        }
        if (previewLoading) { pushStatus("err", "Wait for the preview to finish loading."); return }
        if (!previewRows || previewRows.length === 0) { pushStatus("err", "No products matched this pattern."); return }
        setPendingConfirmation(true)
    }

    async function onConfirm(): Promise<void> {
        const trimmedPat = pattern.trim()
        const trimmedSuffix = skuSuffix.trim()
        const trimmedOv = optionValue.trim()
        const trimmedW = weightGrams.trim()
        const trimmedP = price.trim()
        if (!trimmedPat || !trimmedSuffix || !trimmedOv || !trimmedW || !trimmedP) return
        setSubmitting(true)
        try {
            const result = await runSteppedCatalogJob(
                "/api/add-variant/set/start",
                "/api/add-variant/set/step",
                {
                    pattern: trimmedPat,
                    suffix: trimmedSuffix,
                    optionValue: trimmedOv,
                    weight: Number(trimmedW),
                    price: trimmedP,
                },
            )
            const updated = (result.updated as number) ?? 0
            const userErrors = (result.userErrors as string[]) ?? []
            const warnings = (result.warnings as string[]) ?? []
            const parts = [`Added variant to ${updated} product${updated === 1 ? "" : "s"}.`]
            if (userErrors.length) parts.push(`Shopify: ${userErrors.join("; ")}`)
            if (warnings.length) parts.push(warnings.join(" "))
            pushStatus(userErrors.length > 0 ? "err" : "ok", parts.join(" "))
            setPendingConfirmation(false)
            await loadCatalog(trimmedPat)
        } catch (e) {
            pushStatus("err", e instanceof Error ? e.message : "Could not apply changes.")
        } finally {
            setSubmitting(false)
        }
    }

    function onRevert(): void {
        setPendingConfirmation(false)
    }

    const busy = catalogLoading || submitting
    const trimmedPat = pattern.trim()
    const wNum = Number(weightGrams.trim())
    const pNum = Number(price.trim())
    const weightValid = weightGrams.trim() !== "" && !Number.isNaN(wNum) && wNum >= 0
    const priceValid = price.trim() !== "" && !Number.isNaN(pNum) && pNum > 0
    const catalogReady = loadedPattern === trimmedPat && !catalogLoading && trimmedPat !== ""
    const allFieldsValid = skuSuffix.trim() !== "" && optionValue.trim() !== "" && weightValid && priceValid
    const canSet =
        catalogReady &&
        allFieldsValid &&
        !previewLoading &&
        Boolean(previewRows?.length) &&
        !previewError &&
        !pendingConfirmation
    const controlsLocked = pendingConfirmation

    return (
        <section className="shipping-rates" aria-labelledby="add-variant-heading">
            <h2 id="add-variant-heading" className="shipping-rates__title">
                Add variant to products by SKU pattern
            </h2>
            <div className="shipping-rates__layout">
                <div
                    className={
                        controlsLocked
                            ? "shipping-rates__controls shipping-rates__controls--locked"
                            : "shipping-rates__controls"
                    }
                    aria-busy={controlsLocked}
                >
                    {controlsLocked ? (
                        <p className="shipping-rates__locked-banner" role="status">
                            Review the preview and confirm or revert to continue editing.
                        </p>
                    ) : null}
                    <p className="shipping-rates__list-hint">
                        Enter a regex to match SKUs (case-insensitive), scan to find matching
                        products, fill in the new variant details, then refresh the preview.
                    </p>
                    <form onSubmit={onSubmitSet}>
                        <div className="shipping-rates__row">
                            <div className="shipping-rates__field">
                                <label htmlFor="av-sku-pattern">SKU regex</label>
                                <input
                                    id="av-sku-pattern"
                                    type="text"
                                    autoComplete="off"
                                    placeholder="e.g. ^FO-\d{3}-\d{3}$"
                                    value={pattern}
                                    onChange={(e) => setPattern(e.target.value)}
                                    onKeyDown={(e) => {
                                        if (e.key === "Enter") {
                                            e.preventDefault()
                                            if (trimmedPat && !busy && !controlsLocked) {
                                                void loadCatalog(trimmedPat)
                                            }
                                        }
                                    }}
                                    disabled={busy || controlsLocked}
                                />
                            </div>
                            <button
                                type="button"
                                className="shipping-rates__scan-btn"
                                onClick={() => { if (trimmedPat) void loadCatalog(trimmedPat) }}
                                disabled={busy || !trimmedPat || controlsLocked}
                            >
                                {catalogLoading ? "Scanning…" : "Scan ↺"}
                            </button>
                        </div>
                        <p className="shipping-rates__list-hint">
                            {catalogLoading ? (
                                "Scanning all products…"
                            ) : catalogReady ? (
                                <>{productCount} product{productCount === 1 ? "" : "s"} matched.</>
                            ) : trimmedPat ? (
                                "Press Scan or Enter to load matching products."
                            ) : (
                                "Enter a regex pattern, then press Scan."
                            )}
                        </p>
                        <div className="shipping-rates__row">
                            <div className="shipping-rates__field">
                                <label htmlFor="av-option-value">Option value</label>
                                <input
                                    id="av-option-value"
                                    type="text"
                                    autoComplete="off"
                                    placeholder="e.g. 1kg"
                                    value={optionValue}
                                    onChange={(e) => setOptionValue(e.target.value)}
                                    disabled={busy || !catalogReady || controlsLocked}
                                />
                            </div>
                        </div>
                        <div className="shipping-rates__row">
                            <div className="shipping-rates__field">
                                <label htmlFor="av-sku-suffix">SKU suffix</label>
                                <input
                                    id="av-sku-suffix"
                                    type="text"
                                    autoComplete="off"
                                    placeholder="e.g. 100"
                                    value={skuSuffix}
                                    onChange={(e) => setSkuSuffix(e.target.value)}
                                    disabled={busy || !catalogReady || controlsLocked}
                                />
                            </div>
                        </div>
                        <div className="shipping-rates__row">
                            <div className="shipping-rates__field shipping-rates__field--percent">
                                <label htmlFor="av-weight">Weight (g)</label>
                                <input
                                    id="av-weight"
                                    type="number"
                                    min={0}
                                    step="any"
                                    autoComplete="off"
                                    placeholder="e.g. 1000"
                                    value={weightGrams}
                                    onChange={(e) => setWeightGrams(e.target.value)}
                                    disabled={busy || !catalogReady || controlsLocked}
                                />
                            </div>
                        </div>
                        <div className="shipping-rates__row">
                            <div className="shipping-rates__field shipping-rates__field--percent">
                                <label htmlFor="av-price">Price</label>
                                <input
                                    id="av-price"
                                    type="number"
                                    min={0.01}
                                    step="0.01"
                                    autoComplete="off"
                                    placeholder="e.g. 29.99"
                                    value={price}
                                    onChange={(e) => setPrice(e.target.value)}
                                    disabled={busy || !catalogReady || controlsLocked}
                                />
                            </div>
                        </div>
                        <div className="shipping-rates__row">
                            <button
                                type="button"
                                className="shipping-rates__scan-btn"
                                onClick={() => void refreshPreview()}
                                disabled={
                                    busy || !catalogReady || !allFieldsValid ||
                                    controlsLocked || previewLoading
                                }
                            >
                                {previewLoading ? "Loading…" : "Refresh preview ↺"}
                            </button>
                            <button
                                type="submit"
                                className="shipping-rates__set"
                                disabled={busy || !canSet}
                            >
                                Set
                            </button>
                        </div>
                    </form>
                    <StatusMessageLog entries={statusLog} />
                </div>

                <div
                    className="shipping-rates__preview-wrap"
                    aria-label="Products that will receive a new variant"
                >
                    <h3 className="shipping-rates__preview-title">Preview</h3>
                    {pendingConfirmation ? (
                        <div className="shipping-rates__confirm-bar">
                            <button
                                type="button"
                                className="shipping-rates__btn shipping-rates__btn--confirm"
                                onClick={() => void onConfirm()}
                                disabled={submitting || !previewRows?.length}
                            >
                                {submitting ? "Applying…" : "Confirm"}
                            </button>
                            <button
                                type="button"
                                className="shipping-rates__btn shipping-rates__btn--revert"
                                onClick={onRevert}
                                disabled={submitting}
                            >
                                Revert
                            </button>
                        </div>
                    ) : null}
                    {catalogLoading ? (
                        <p className="shipping-rates__loading">Scanning products for matching SKUs…</p>
                    ) : !catalogReady ? (
                        <p className="shipping-rates__preview-empty">
                            Enter a SKU regex and press Scan to find matching products.
                        </p>
                    ) : previewLoading ? (
                        <p className="shipping-rates__loading">Loading preview…</p>
                    ) : previewError ? (
                        <p className="shipping-rates__preview-empty" role="alert">
                            {previewError}
                        </p>
                    ) : !previewRows ? (
                        <p className="shipping-rates__preview-empty">
                            {productCount === 0
                                ? "No products matched this pattern."
                                : "Fill in the variant details and press Refresh preview."}
                        </p>
                    ) : previewRows.length === 0 ? (
                        <p className="shipping-rates__preview-empty">
                            No products matched this SKU pattern.
                        </p>
                    ) : (
                        <div className="shipping-rates__preview">
                            {previewWarnings ? (
                                <p className="shipping-rates__preview-note">{previewWarnings}</p>
                            ) : null}
                            <table className="shipping-rates__sku-table">
                                <thead>
                                    <tr>
                                        <th>Product</th>
                                        <th>New SKU</th>
                                        <th>Option value</th>
                                        <th>Weight</th>
                                        <th>Price</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {previewRows.map((row) => (
                                        <tr key={row.productId}>
                                            <td>{row.productTitle}</td>
                                            <td className="shipping-rates__sku-table-sku">{row.newSku}</td>
                                            <td>{row.optionValue}</td>
                                            <td>{row.weightGrams} g</td>
                                            <td>{row.price}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </div>
        </section>
    )
}
```

- [ ] **Step 2: Commit**

```bash
git add src/frontend/tsxsrc/AddVariantPanel.tsx
git commit -m "feat: add AddVariantPanel component"
```

---

### Task 10: Wire up in `app.tsx`

**Files:**
- Modify: `src/frontend/tsxsrc/app.tsx`

- [ ] **Step 1: Add import at top of `app.tsx`**

After the existing `SkuWeightPanel` import line, add:

```tsx
import AddVariantPanel from "./AddVariantPanel"
```

- [ ] **Step 2: Extend the `TabId` union type**

Change:
```tsx
type TabId = "shipping" | "products" | "orders" | "skuweight"
```
to:
```tsx
type TabId = "shipping" | "products" | "orders" | "skuweight" | "addvariant"
```

- [ ] **Step 3: Add the tab button inside `<div className="app-tabs__bar">`**

After the existing `skuweight` button block, add:

```tsx
                    <button
                        type="button"
                        role="tab"
                        id="tab-addvariant"
                        className={
                            tab === "addvariant"
                                ? "app-tabs__tab app-tabs__tab--active"
                                : "app-tabs__tab"
                        }
                        aria-selected={tab === "addvariant"}
                        aria-controls="panel-addvariant"
                        onClick={() => setTab("addvariant")}
                    >
                        Add variant
                    </button>
```

- [ ] **Step 4: Add the tab panel inside the panels block**

After the closing `</div>` of `panel-skuweight`, add:

```tsx
                <div
                    id="panel-addvariant"
                    role="tabpanel"
                    className="app-tabs__panel"
                    aria-labelledby="tab-addvariant"
                    hidden={tab !== "addvariant"}
                >
                    <AddVariantPanel />
                </div>
```

- [ ] **Step 5: Build frontend to verify no TypeScript errors**

```bash
cd /Users/user/Dev/morebuttons && npm run build 2>&1 | tail -20
```

Expected: build succeeds with no errors.

- [ ] **Step 6: Run full backend test suite one final time**

```bash
cd /Users/user/Dev/morebuttons && .venv/bin/pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/frontend/tsxsrc/app.tsx
git commit -m "feat: wire Add variant tab into app"
```
