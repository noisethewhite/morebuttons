from enum import StrEnum


class Routes(StrEnum):
    API = "/api"
    WEBHOOKS = "/webhooks"
    APP_UNINSTALLED = "/webhooks/app-uninstalled"
    SHIPPING_RATE_NAMES = f"{API}/shipping-rate-names"
    SHIPPING_RATES_ADJUST = f"{API}/shipping-rates/adjust"
    SHIPPING_RATES_PREVIEW = f"{API}/shipping-rates/preview"
    GRAPHQL_MUTATION_ALLOW = f"{API}/graphql-mutation-allow"
