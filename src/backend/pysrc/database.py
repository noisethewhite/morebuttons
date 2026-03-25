import sqlalchemy as sqla
import sqlalchemy.dialects.postgresql as psql
from typing import Any
import enum
import heresy
from .environment import Environment


def _normalize_database_url(url: str) -> str:
    # Heroku sets DATABASE_URL with postgres://; SQLAlchemy + psycopg2 expect postgresql://
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


@heresy.singleton
class Database(object):
    _engine: sqla.Engine

    def __init__(self) -> None:
        self._engine = sqla.create_engine(
            _normalize_database_url(str(Environment.database_url)),
            pool_pre_ping=True,
            echo=False
        )

    @heresy.singletonproperty
    def engine(self) -> sqla.Engine:
        return self._engine

    @heresy.singletonmethod
    def execute(self, statement: sqla.Executable, commit: bool = True) -> sqla.CursorResult[Any]:
        with self._engine.connect() as conn:
            result = conn.execute(statement)
            if commit:
                conn.commit()
            return result

    @heresy.singleton
    class AccessTokens(object):
        TABLE_NAME = "shop_tokens"
        SCHEMA     = "00_secrets"

        class Columns(enum.StrEnum):
            DOMAIN = "shop_domain"
            TOKEN  = "access_token"

        _metadata: sqla.MetaData
        _table: sqla.Table

        def __init__(self) -> None:
            self._metadata = sqla.MetaData()
            self._table = sqla.Table(
                self.TABLE_NAME,
                self._metadata,
                sqla.Column(self.Columns.DOMAIN, sqla.Text, primary_key=True),
                sqla.Column(self.Columns.TOKEN, sqla.Text, nullable=False),
                schema=self.SCHEMA
            )
            self._metadata.create_all(Database.engine)

        @heresy.singletonmethod
        def set_token(self, shop_domain: str, access_token: str) -> None:
            statement = psql \
                .insert(self._table) \
                .values({
                    self.Columns.DOMAIN: shop_domain,
                    self.Columns.TOKEN: access_token
                }) \
                .on_conflict_do_update(
                    index_elements=[self.Columns.DOMAIN],
                    set_={ self.Columns.TOKEN: access_token }
                )
            Database.execute(statement)

        @heresy.singletonmethod
        def get_token(self, shop_domain: str) -> str | None:
            statement = sqla \
                .select(self._table.c[self.Columns.TOKEN]) \
                .where(self._table.c[self.Columns.DOMAIN] == shop_domain)
            access_token = Database \
                .execute(statement, commit=False) \
                .scalar_one_or_none()
            if access_token is not None and not isinstance(access_token, str):
                raise RuntimeError("Tried to get_access_token; it is not a string.")
            return access_token

        @heresy.singletonmethod
        def delete_token(self, shop_domain: str) -> None:
            statement = sqla \
                .delete(self._table) \
                .where(self._table.c[self.Columns.DOMAIN] == shop_domain)
            Database.execute(statement)

    @heresy.singleton
    class Webhooks(object):
        TABLE_NAME = "shop_webhooks"
        SCHEMA     = "00_secrets"

        class Columns(enum.StrEnum):
            DOMAIN   = "shop_domain"
            WEBHOOKS = "webhooks"

        _metadata: sqla.MetaData
        _table: sqla.Table

        def __init__(self) -> None:
            self._metadata = sqla.MetaData()
            self._table = sqla.Table(
                self.TABLE_NAME,
                self._metadata,
                sqla.Column(self.Columns.DOMAIN, sqla.Text, primary_key=True),
                sqla.Column(self.Columns.WEBHOOKS, psql.ARRAY(sqla.Text), nullable=False),
                schema=self.SCHEMA
            )
            self._metadata.create_all(Database.engine)

        @heresy.singletonmethod
        def set_webhooks(self, shop_domain: str, webhooks: list[str]) -> None:
            statement = psql \
                .insert(self._table) \
                .values({
                    self.Columns.DOMAIN: shop_domain,
                    self.Columns.WEBHOOKS: webhooks
                }) \
                .on_conflict_do_update(
                    index_elements=[self.Columns.DOMAIN],
                    set_={ self.Columns.WEBHOOKS: webhooks }
                )
            Database.execute(statement)

        @heresy.singletonmethod
        def get_webhooks(self, shop_domain: str) -> list[str] | None:
            statement = sqla \
                .select(self._table.c[self.Columns.WEBHOOKS]) \
                .where(self._table.c[self.Columns.DOMAIN] == shop_domain)
            row = Database.execute(statement, commit=False).scalar_one_or_none()
            if row is None:
                return None
            if not isinstance(row, list):
                raise RuntimeError("Webhooks column is not a list.")
            return [str(x) for x in row]

        @heresy.singletonmethod
        def add_webhook_id(self, shop_domain: str, webhook_id: str) -> None:
            existing = self.get_webhooks(shop_domain) or []
            if webhook_id not in existing:
                existing.append(webhook_id)
            self.set_webhooks(shop_domain, existing)

        @heresy.singletonmethod
        def delete_row(self, shop_domain: str) -> None:
            statement = sqla \
                .delete(self._table) \
                .where(self._table.c[self.Columns.DOMAIN] == shop_domain)
            Database.execute(statement)
