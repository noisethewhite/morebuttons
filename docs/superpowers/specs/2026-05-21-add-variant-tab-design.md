# Add Variant Tab — Design Spec

**Date:** 2026-05-21  
**Status:** Approved

---

## Overview

A new fifth tab — **"Add variant"** — that finds all Shopify products whose existing variants contain SKUs matching a user-supplied regex, then adds one new variant to each matched product. The variant's SKU is constructed per-product from an auto-derived product base prefix plus a user-entered suffix. The tab is visually and structurally identical to the existing "SKU weights" tab.

---

## User flow

1. Enter a SKU regex (e.g. `FO-\d{3}-\d{3}`) and press **Scan**.
2. The backend paginates all products, finds those with at least one variant SKU matching the pattern, and caches the results.
3. Fill in the four variant fields: **Option value**, **SKU suffix**, **Weight (g)**, **Price**.
4. Press **Refresh preview** — the right column populates with one row per matched product showing the computed new SKU, option value, weight, and price. Fields do **not** auto-update as the user types; preview only refreshes on explicit button press.
5. If any matched product already has a variant whose SKU equals the computed new SKU for that product, the preview shows a blocking error and **Set** is disabled.
6. Press **Set** → confirm/revert bar appears.
7. **Confirm** runs the stepped apply job (one `productVariantsBulkCreate` call per product). **Revert** cancels without changes.

---

## SKU construction

Products do not have a top-level SKU in Shopify — only variants do. The product base prefix is derived automatically:

> Take any matching variant SKU for the product, split on `-`, drop the last segment, rejoin with `-`.

Examples:
- `FO-101-001` → prefix `FO-101`
- `FO-102-005` → prefix `FO-102`

New variant SKU per product = `{prefix}-{userSuffix}`

So entering suffix `100` produces `FO-101-100`, `FO-102-100`, etc.

---

## Architecture

Follows the exact pattern of `SkuWeightPanel` / `SkuWeightCatalogJob` / `SkuWeightApplyJob`.

### New backend files

| File | Purpose |
|---|---|
| `pysrc/add_variant_job.py` | Stepped catalog scan job |
| `pysrc/add_variant_apply_job.py` | Stepped apply job (productVariantsBulkCreate) |
| `pysrc/add_variant_preview.py` | Preview logic (reads cache, checks conflicts) |
| `graphql/products_add_variant_page.gql` | Paginated product query with options |
| `graphql/product_variants_bulk_create.gql` | Create-variant mutation |

### New frontend file

| File | Purpose |
|---|---|
| `tsxsrc/AddVariantPanel.tsx` | Tab panel component |

### Modified existing files

| File | Change |
|---|---|
| `pysrc/catalog_cache.py` | Add `_add_variant_catalog` dict + get/set/invalidate |
| `pysrc/graphqldc/products.py` | New dataclasses for query/mutation/step results |
| `pysrc/routes.py` | 5 new route constants |
| `backend/main.py` | 5 new route handlers |
| `tsxsrc/app.tsx` | New tab button + panel |

---

## Backend detail

### Catalog scan job

**GQL query** (`products_add_variant_page.gql`): same pagination as `products_sku_weight_page.gql`, adds `options(first: 1) { name }` per product and fetches variant `sku` fields.

**Job** (`AddVariantCatalogJob`):
- Paginates products 50 at a time
- For each product, checks whether any variant SKU matches the compiled regex
- If matched: records `productId`, `productTitle`, `firstOptionName` (from `options[0].name`, defaulting to `"Title"` if absent), `baseSkuPrefix` (derived from first matching variant SKU by splitting on `-` and dropping the last segment), and `allVariantSkus` (every variant SKU for that product — used for complete conflict detection)
- Warns if a product has > 100 variants (only first page loaded)
- Stores result in `_add_variant_catalog[shopDomain, pattern]`

**Routes:** `POST /api/add-variant-catalog/start`, `POST /api/add-variant-catalog/step`

### Preview endpoint

**Route:** `GET /api/add-variant/preview?pattern=&suffix=&optionValue=&weight=&price=`

1. Reads `_add_variant_catalog[shopDomain, pattern]` — 400 if not loaded
2. Computes `newSku = row.baseSkuPrefix + "-" + suffix` for each row
3. Conflict check: for each product row, checks `row.allVariantSkus` for `newSku`; if any match, collects conflict. If conflicts exist, returns `{ error: "N product(s) already have a variant with SKU …" }` with no rows.
4. Otherwise returns `{ rows: [{productId, productTitle, newSku, optionValue, weight, price}], warnings }`

### Apply job

**Job** (`AddVariantApplyJob`):
- Initialised with the full cached catalog rows plus user inputs (`suffix`, `optionValue`, `weightG`, `price`)
- Computes `newSku = row.baseSkuPrefix + "-" + suffix` per row at init time, building a task list of `(productId, firstOptionName, newSku)` tuples
- One step = one product: calls `productVariantsBulkCreate(productId, variants: [{ price, sku: newSku, optionValues: [{optionName: firstOptionName, name: optionValue}], inventoryItem: { measurement: { weight: { value: weightG, unit: "GRAMS" } } } }])`
- Collects `updated` count and `userErrors`
- On finish: invalidates the catalog cache entry for this pattern

**Routes:** `POST /api/add-variant/set/start`, `POST /api/add-variant/set/step`

---

## Frontend detail

### `AddVariantPanel.tsx`

State mirrors `SkuWeightPanel`:
- `pattern`, `catalogLoading`, `loadedPattern`, `productCount`
- `optionValue`, `skuSuffix`, `weightGrams`, `price` — four controlled inputs
- `previewRows`, `previewLoading`, `previewError`, `previewWarnings` — populated only on explicit **Refresh preview** button press, not on field change
- `pendingConfirmation`, `submitting`
- `statusLog`

**Preview update trigger:** only the **Refresh preview** button calls the preview endpoint. No `useEffect` watching field values.

**Preview table columns:** Product | New SKU | Option value | Weight | Price

**Conflict display:** if the preview response contains `error`, render the error message in place of the table and disable **Set**.

**Set button enabled when:** catalog ready + all four fields valid + preview loaded without error + not `pendingConfirmation`.

**Confirm/Revert bar:** identical to `SkuWeightPanel` — appears when `pendingConfirmation`, calls the stepped apply job on confirm.

---

## Error handling

| Scenario | Behaviour |
|---|---|
| Invalid regex | Catalog job sets `exhausted=True`, returns warning; frontend shows in status log |
| Product has > 100 variants | Warning added to catalog result; shown in preview note |
| SKU conflict | Preview returns `error`; Set disabled; message shown in preview area |
| Shopify user error on create | Collected in `userErrors`, shown in status log after apply |
| Network / 502 | Same retry logic as `runSteppedCatalogJob` (3 retries with backoff) |

---

## New API routes summary

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/add-variant-catalog/start` | Start catalog scan job |
| POST | `/api/add-variant-catalog/step` | Step catalog scan job |
| GET | `/api/add-variant/preview` | Preview new variants |
| POST | `/api/add-variant/set/start` | Start apply job |
| POST | `/api/add-variant/set/step` | Step apply job |
