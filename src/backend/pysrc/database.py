import sqlalchemy as sqla
import sqlalchemy.dialects.postgresql as psql
from typing import TypeVar, Protocol, override, overload
import enum
import heresy
from .environment import Environment


_T = TypeVar("_T")


class Stringable(Protocol):
    @override
    def __str__(self) -> str: ...


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
    @overload
    def execute(self, _statement: sqla.Executable, _expected_type: None) -> None: ...

    @heresy.singletonmethod
    @overload
    def execute(self, _statement: sqla.Executable, _expected_type: type[_T]) -> _T: ...

    @heresy.singletonmethod
    def execute(
        self,
        _statement: sqla.Executable,
        _expected_type: type[_T] | None = None
    ) -> _T | None:
        commit = _expected_type is None
        with self._engine.connect() as conn:
            result: sqla.CursorResult[_T] = conn.execute(_statement)
            if commit:
                conn.commit()
            if _expected_type is not None:
                value= result.scalar_one_or_none()
                if value is not None and not isinstance(value, _expected_type):
                    raise RuntimeError(f"Expected {_expected_type}, got {type(value)}.")  # pyright: ignore[reportAny]
                return value
            return None

    @heresy.singleton
    class AccessTokens(object):
        TABLE_NAME: str = "shop_tokens"
        SCHEMA    : str = "00_secrets"

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
            return Database.execute(statement, str)

        @heresy.singletonmethod
        def delete_token(self, shop_domain: str) -> None:
            statement = sqla \
                .delete(self._table) \
                .where(self._table.c[self.Columns.DOMAIN] == shop_domain)
            Database.execute(statement)

    @heresy.singleton
    class Webhooks(object):
        TABLE_NAME: str = "shop_webhooks"
        SCHEMA    : str = "00_secrets"

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
            row = Database.execute(statement, list[str])
            if row is None:
                return None
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

    @heresy.singleton
    class MutationAllow(object):
        TABLE_NAME: str = "shop_mutation_allow"
        SCHEMA: str = "00_secrets"

        class Columns(enum.StrEnum):
            DOMAIN = "shop_domain"
            ALLOW = "allow_graphql_mutations"

        _metadata: sqla.MetaData
        _table: sqla.Table

        def __init__(self) -> None:
            self._metadata = sqla.MetaData()
            self._table = sqla.Table(
                self.TABLE_NAME,
                self._metadata,
                sqla.Column(self.Columns.DOMAIN, sqla.Text, primary_key=True),
                sqla.Column(self.Columns.ALLOW, sqla.Boolean, nullable=False, server_default=sqla.false()),
                schema=self.SCHEMA,
            )
            self._metadata.create_all(Database.engine)

        @heresy.singletonmethod
        def get_allow(self, shop_domain: str) -> bool:
            statement = sqla \
                .select(self._table.c[self.Columns.ALLOW]) \
                .where(self._table.c[self.Columns.DOMAIN] == shop_domain)
            row = Database.execute(statement, bool)
            return bool(row) if row is not None else False

        @heresy.singletonmethod
        def set_allow(self, shop_domain: str, allow: bool) -> None:
            statement = psql \
                .insert(self._table) \
                .values({
                    self.Columns.DOMAIN: shop_domain,
                    self.Columns.ALLOW: allow,
                }) \
                .on_conflict_do_update(
                    index_elements=[self.Columns.DOMAIN],
                    set_={self.Columns.ALLOW: allow},
                )
            Database.execute(statement)
