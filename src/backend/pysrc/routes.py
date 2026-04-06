from enum import StrEnum


class Routes(StrEnum):
    API = "/api"
    WEBHOOKS = "/webhooks"
    APP_UNINSTALLED = "/webhooks/app-uninstalled"
    SHIPPING_RATE_NAMES = f"{API}/shipping-rate-names"
    SHIPPING_RATES_ADJUST = f"{API}/shipping-rates/adjust"
    SHIPPING_RATES_PREVIEW = f"{API}/shipping-rates/preview"
    SHIPPING_CATALOG_START = f"{API}/shipping-catalog/start"
    SHIPPING_CATALOG_STEP = f"{API}/shipping-catalog/step"
    PRODUCT_TAGS = f"{API}/product-tags"
    PRODUCT_TAG_CATALOG_START = f"{API}/product-tag-catalog/start"
    PRODUCT_TAG_CATALOG_STEP = f"{API}/product-tag-catalog/step"
    PRODUCT_TAG_PRICING_PREVIEW = f"{API}/product-tag-pricing/preview"
    PRODUCT_TAG_PRICING_ADJUST = f"{API}/product-tag-pricing/adjust"
    GRAPHQL_MUTATION_ALLOW = f"{API}/graphql-mutation-allow"
