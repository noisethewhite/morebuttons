# Order Lookup Tab — Design Spec

**Date:** 2026-05-12  
**Status:** Approved

---

## Overview

Add a third tab, "Order lookup", to the existing Shopify admin app (which already has "Delivery rates" and "Product tag prices" tabs). The tab lets a user enter a tracking number and look up the associated order. A carrier pre-filter is populated by scanning the last N orders within a user-chosen date range via a stepped background job (same pattern as the existing shipping and product-tag catalog jobs).

---

## New Files

| Path | Purpose |
|---|---|
| `src/backend/graphql/order_carrier_catalog_page.gql` | Paginated orders query — only `fulfillments.trackingInfo.company` + `pageInfo` |
| `src/backend/graphql/order_by_tracking.gql` | Full order lookup query by tracking number |
| `src/backend/pysrc/graphqldc/orders.py` | Pydantic dataclasses for all order-related GQL types and API response shapes |
| `src/backend/pysrc/order_carrier_job.py` | Stepped job that paginates Shopify orders and collects unique carrier names |
| `src/backend/pysrc/order_lookup.py` | `lookup_order_by_tracking()` function |
| `src/frontend/tsxsrc/OrderLookupPanel.tsx` | New tab panel component |
| `src/frontend/styles/order-lookup.css` | BEM styles, prefix `order-lookup__` |

---

## Routes

Three new entries in `src/backend/pysrc/routes.py`:

```
ORDER_CARRIER_CATALOG_START = /api/order-carrier-catalog/start
ORDER_CARRIER_CATALOG_STEP  = /api/order-carrier-catalog/step
ORDER_BY_TRACKING           = /api/order-by-tracking
```

Three new route handlers in `src/backend/main.py` following the same structure as the existing catalog start/step/lookup handlers.

---

## Dataclasses — `graphqldc/orders.py`

Uses `pydantic.dataclasses` with `ConfigDict(extra="ignore")` throughout, identical to `graphqldc/shipping.py` and `graphqldc/products.py`.

### Shared types

```python
MoneyV2(amount: str, currencyCode: str)
# Shopify MoneyV2: amount is Decimal! (JSON decimal string), currencyCode is CurrencyCode!

MoneyBag(shopMoney: MoneyV2, presentmentMoney: MoneyV2 | None = None)
# Shopify MoneyBag: shopMoney: MoneyV2!, presentmentMoney: MoneyV2!
# presentmentMoney optional here for defensive parsing only

FulfillmentTrackingInfo(number: str | None, company: str | None, url: str | None)
# Shopify FulfillmentTrackingInfo: number: String, company: String, url: URL
# All three fields are nullable in the API

FulfillmentNode(trackingInfo: list[FulfillmentTrackingInfo])
# Shopify Fulfillment.trackingInfo: [FulfillmentTrackingInfo!]! (non-null array)
```

### For `order_carrier_catalog_page.gql`

```python
OrderCarrierNode(fulfillments: list[FulfillmentNode])
# Shopify Order.fulfillments: [Fulfillment!]! (non-null)

OrderCarrierCatalogData(orders: Connection[OrderCarrierNode])
```

### For `order_by_tracking.gql`

```python
MailingAddress(
    address1: str | None, address2: str | None,
    city: str | None, province: str | None,
    country: str | None, zip: str | None,
    countryCodeV2: str | None,
)
# All fields nullable in Shopify MailingAddress
# countryCodeV2: CountryCode (enum, serialised as string)

CustomerNode(firstName: str | None, lastName: str | None)
# Shopify Customer.firstName/lastName: String (nullable)

ShippingLine(
    title: str,                          # String! (non-null)
    originalPriceSet: MoneyBag,          # MoneyBag! (non-null)
    discountedPriceSet: MoneyBag | None, # MoneyBag!
    carrierIdentifier: str | None,       # String
    code: str | None,                    # String
)

OrderNode(
    id: str,                             # ID! (non-null)
    name: str,                           # String! (non-null, e.g. "#1234")
    displayFulfillmentStatus: str,       # OrderDisplayFulfillmentStatus! (enum → str)
    fulfillments: list[FulfillmentNode], # [Fulfillment!]! (non-null array)
    currentTotalPriceSet: MoneyBag,      # MoneyBag! (non-null)
    customer: CustomerNode | None,       # Customer (nullable — None for guest checkouts)
    shippingAddress: MailingAddress | None,  # MailingAddress (nullable)
    totalWeight: int | None,             # UnsignedInt64 (nullable, in grams)
    shippingLine: ShippingLine | None,   # ShippingLine (nullable)
)

OrdersByTrackingData(orders: Connection[OrderNode])
```

### API response shapes (extend `Jsonable`)

```python
OrderResultAddress(
    address1: str | None, address2: str | None,
    city: str | None, province: str | None,
    country: str | None, zip: str | None,
    countryCode: str | None,
)

OrderResult(
    orderNumber: str,           # e.g. "#1234"
    status: str,                # displayFulfillmentStatus value
    customerName: str,          # firstName + lastName, or "Guest" if None
    address: OrderResultAddress | None,
    weightGrams: int | None,
    deliveryCost: str | None,   # formatted e.g. "€5.90" via Currency.format_amount
    deliveryTitle: str | None,  # ShippingLine.title
    orderTotal: str | None,     # formatted from currentTotalPriceSet.shopMoney
)

OrderCarrierStepPending(done=False, completed: int, remaining: int, total: int, phase="order_carrier")
OrderCarrierStepDone(done=True, completed: int, total: int, remaining=0, carriers: list[str], phase="order_carrier")
```

---

## GraphQL Queries

### `order_carrier_catalog_page.gql`

```graphql
query OrderCarrierPage($first: Int!, $after: String, $query: String) {
  orders(first: $first, after: $after, query: $query, sortKey: CREATED_AT, reverse: true) {
    edges {
      node {
        fulfillments {
          trackingInfo {
            company
          }
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
```

### `order_by_tracking.gql`

```graphql
query OrderByTracking($query: String!) {
  orders(first: 10, query: $query) {
    edges {
      node {
        id
        name
        displayFulfillmentStatus
        customer {
          firstName
          lastName
        }
        shippingAddress {
          address1
          address2
          city
          province
          country
          zip
          countryCodeV2
        }
        totalWeight
        shippingLine {
          title
          originalPriceSet {
            shopMoney {
              amount
              currencyCode
            }
          }
        }
        currentTotalPriceSet {
          shopMoney {
            amount
            currencyCode
          }
        }
        fulfillments {
          trackingInfo {
            number
            company
            url
          }
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
```

---

## Stepped Job — `order_carrier_job.py`

```python
@dataclass
class OrderCarrierJob:
    id: str
    shop_domain: str
    token: str
    max_orders: int           # user-supplied cap; stops pagination when reached
    date_from: str | None     # ISO date string e.g. "2024-01-01", used in Shopify query
    date_to: str | None       # ISO date string e.g. "2024-12-31"
    carriers: set[str]        # accumulated unique non-empty carrier names
    orders_scanned: int       # running count across steps
    after: str | None         # pagination cursor
    exhausted: bool           # True when hasNextPage is False or max_orders reached
    completed_steps: int
```

**Step logic:**
1. Build Shopify query string from `date_from` / `date_to`:  
   e.g. `"created_at:>=2024-01-01 created_at:<=2024-12-31"` (omit clauses if date is None)
2. Fetch up to `min(250, max_orders - orders_scanned)` orders per step
3. For each `OrderCarrierNode`, iterate `fulfillments → trackingInfo → company`; add non-empty strings to `carriers`
4. Increment `orders_scanned` by the number of edges returned
5. If `hasNextPage is False` or `orders_scanned >= max_orders`, set `exhausted = True`
6. Return `OrderCarrierStepPending` or `OrderCarrierStepDone` serialised via `.to_json()`

**Finish:** `OrderCarrierStepDone` with `carriers` as a sorted list.

Module-level `_JOBS: dict[str, OrderCarrierJob]` with `create_`, `take_`, `delete_` helpers — identical pattern to `shipping_catalog_job.py`.

---

## Lookup Function — `order_lookup.py`

```python
def lookup_order_by_tracking(
    shop_domain: str,
    token: str,
    tracking_number: str,
    carrier: str | None = None,
) -> tuple[list[OrderResult], list[str]]:
```

1. Build Shopify search query: `f"tracking_number:{tracking_number}"`
2. Call `GraphQL.send(..., expected_type=OrdersByTrackingData)`
3. If `carrier` is not None, filter `OrderNode` list: keep only orders where any `fulfillment.trackingInfo` entry has `company == carrier` (case-insensitive)
4. Convert each surviving `OrderNode` → `OrderResult`:
   - `orderNumber = node.name`
   - `status = node.displayFulfillmentStatus`
   - `customerName = f"{firstName} {lastName}".strip() or "Guest"`
   - `address` from `node.shippingAddress`
   - `weightGrams = node.totalWeight`
   - `deliveryCost` = `Currency.format_amount(shopMoney.amount, shopMoney.currencyCode)` from `shippingLine.originalPriceSet`
   - `deliveryTitle = shippingLine.title`
   - `orderTotal` = formatted from `currentTotalPriceSet.shopMoney`
5. Return `(results, warnings)`

---

## Backend Route Handlers (`main.py`)

### `POST /api/order-carrier-catalog/start`
Body: `{ dateFrom?: string, dateTo?: string, maxOrders?: number }`  
Validates `maxOrders` (default 1000, clamped to 1–10000).  
Creates `OrderCarrierJob`, returns `{ jobId }`.

### `POST /api/order-carrier-catalog/step`
Body: `{ jobId: string }`  
Advances the job one step. Returns `OrderCarrierStepPending | OrderCarrierStepDone`.  
Deletes the job when `done = true`.

### `GET /api/order-by-tracking`
Query params: `trackingNumber` (required), `carrier` (optional, omit for All).  
Returns `{ orders: OrderResult[], warnings: string[] }`.

---

## Frontend — `app.tsx`

Extend `TabId = "shipping" | "products" | "orders"`.  
Add a third tab button ("Order lookup") and panel wrapping `<OrderLookupPanel />`.

---

## Frontend — `OrderLookupPanel.tsx`

### Carrier loader section

Controls:
- `<input type="date">` for **From** date (optional)
- `<input type="date">` for **To** date (optional)
- `<input type="number">` for **Max orders** (default 1000)
- **Refresh** button — starts a new `runSteppedCatalogJob` call to the two carrier catalog endpoints
- Progress bar while job runs (same `runSteppedCatalogJob` helper used by other tabs)

On job completion, the `carriers` array from the `done` response populates the dropdown.

### Carrier dropdown

`<select>` with an "All" option (value `""`) plus one option per carrier string from the job result. Disabled while job is running.

### Tracking lookup section

- `<input type="text">` for tracking number
- **Look up** button — `GET /api/order-by-tracking?trackingNumber=…[&carrier=…]`
- Inline error / empty state below the button

### Result cards

One card per returned `OrderResult`:

```
Order #1234          FULFILLED
Customer  Jane Smith
Address   123 Main St, Berlin, 10115, DE
Weight    1 200 g
Delivery  €5.90  (DHL Express)
Total     €49.90
```

Multiple cards stacked vertically if multiple orders match.

---

## CSS — `order-lookup.css`

BEM prefix `order-lookup__`. Follows the structure of `shipping-rates.css`:
- `.order-lookup` — section wrapper
- `.order-lookup__loader` — carrier loader area
- `.order-lookup__loader-row` — date/maxOrders/refresh controls in a row
- `.order-lookup__progress` — progress bar
- `.order-lookup__carrier-row` — dropdown row
- `.order-lookup__search-row` — tracking input + button
- `.order-lookup__results` — card list
- `.order-lookup__card` — individual result card
- `.order-lookup__card-row` — label + value row within a card

---

## Error Handling

- Missing or blank `trackingNumber` → 400 from backend
- No matching orders → empty `orders` array (frontend shows "No orders found")
- Multiple matches → all shown as cards, with a note if `pageInfo.hasNextPage` is true ("More than 10 results — refine your search")
- Carrier job GraphQL failure → `warnings` included in step response; job reports done with whatever carriers were collected
- Guest checkout → `customerName = "Guest"`, `address = null` displayed as "—"

---

## Out of Scope

- Mutations (this tab is read-only)
- Caching carrier results between sessions
- Pagination of tracking lookup results beyond the first 10 matches
