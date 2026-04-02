from typing import Self
from enum import StrEnum
import os


class _NamedString(str):
    _name: str

    def __new__(cls, name: str, value: str) -> Self:
        obj = super().__new__(cls, value)
        obj._name = name
        return obj

    @property
    def name(self) -> str:
        return self._name

    @property
    def value(self) -> str:
        return self


class _EnvEnum(StrEnum):
    def __get__(self, instance: Self | None, owner: type[Self]) -> _NamedString:
        value = _NamedString(self.value, os.environ.get(self) or "")
        if not value:
            missing = [
                name.value for name in owner
                if not os.environ.get(name.value)
            ]
            raise RuntimeError(f"Some environment variables are missing: {' ,'.join(missing)}.")
        return value


class Environment(_EnvEnum):
    shopify_api_key     = "SHOPIFY_API_KEY"
    shopify_secret      = "SHOPIFY_SECRET"
    shopify_api_version = "SHOPIFY_API_VERSION"
    database_url        = "DATABASE_URL"
    flask_secret_key    = "FLASK_SECRET_KEY"
    public_app_url      = "SHOPIFY_APP_URL"
