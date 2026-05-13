from enum import StrEnum


class Routes(StrEnum):
    API = "/api"
    WEBHOOKS = "/webhooks"
    APP_UNINSTALLED = "/webhooks/app-uninstalled"
    SHIPPING_RATE_NAMES = f"{API}/shipping-rate-names"
    SHIPPING_RATES_ADJUST = f"{API}/shipping-rates/adjust"
    SHIPPING_RATES_PREVIEW = f"{API}/shipping-rates/preview"
    SHIPPING_RATES_CSV = f"{API}/shipping-rates/csv"
    SHIPPING_RATES_CSV_PROVINCES = f"{API}/shipping-rates/csv-provinces"
    SHIPPING_CATALOG_START = f"{API}/shipping-catalog/start"
    SHIPPING_CATALOG_STEP = f"{API}/shipping-catalog/step"
    PRODUCT_TAGS = f"{API}/product-tags"
    PRODUCT_TAG_CATALOG_START = f"{API}/product-tag-catalog/start"
    PRODUCT_TAG_CATALOG_STEP = f"{API}/product-tag-catalog/step"
    PRODUCT_TAG_PRICING_PREVIEW = f"{API}/product-tag-pricing/preview"
    PRODUCT_TAG_PRICING_ADJUST = f"{API}/product-tag-pricing/adjust"
    GRAPHQL_MUTATION_ALLOW = f"{API}/graphql-mutation-allow"
    ORDER_CARRIER_CATALOG_START = f"{API}/order-carrier-catalog/start"
    ORDER_CARRIER_CATALOG_STEP  = f"{API}/order-carrier-catalog/step"
    ORDER_BY_TRACKING           = f"{API}/order-by-tracking"
    ORDER_LOOKUP_CSV            = f"{API}/order-lookup/csv"
