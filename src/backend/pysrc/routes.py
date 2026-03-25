from enum import StrEnum


class Routes(StrEnum):
    API = "/api"
    WEBHOOKS = "/webhooks"
    APP_UNINSTALLED = "/webhooks/app-uninstalled"
