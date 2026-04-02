from __future__ import annotations

import requests
import flask
from flask import has_request_context
from typing import Literal, TypeVar, cast, overload, Protocol, ClassVar
import dataclasses
from .environment import Environment
from .database import Database
from .fileloader import FileLoader
from .graphql_counters import classify_graphql_operation, increment_request_graphql
from .rate_limiter import GraphQLThrottled, graphql_rate_limit, is_graphql_throttled_payload
from .utils import Utils
from .web_types import Json


class DataclassProtocol(Protocol):
    __dataclass_fields__: ClassVar[dict[str, dataclasses.Field[object]]]


_DC = TypeVar("_DC", bound=DataclassProtocol)


class MutationsBlockedError(Exception):
    """Raised when a GraphQL mutation is attempted while mutations are disabled."""


def mutations_allowed_from_g() -> bool:
    """
    Whether Shopify GraphQL mutations may run for interactive API traffic.
    Set from the database per shop on each request (see main.sync_mutation_allow_to_g).
    """
    if not has_request_context():
        return True
    return bool(getattr(flask.g, "allow_graphql_mutations", False))


class GraphQL(object):
    @staticmethod
    def extract_errors(gql: Json.Value) -> list[str]:
        if not isinstance(gql, dict):
            return ["Invalid GraphQL response."]
        errs = gql.get("errors")
        if not isinstance(errs, list) or not errs:
            return []
        out: list[str] = []
        for e in errs:
            if isinstance(e, dict):
                msg = e.get("message")
                if isinstance(msg, str):
                    out.append(msg)
            else:
                out.append(repr(e))
        return out

    @staticmethod
    def response_data(gql: Json.Value) -> Json.Object | None:
        """Top-level ``data`` object from a Shopify Admin GraphQL JSON response."""
        if not isinstance(gql, dict):
            return None
        d = gql.get("data")
        return d if isinstance(d, dict) else None

    @staticmethod
    @overload
    def send(
        shop_domain: str,
        access_token: str,
        query: str,
        variables: Json.Object | None = None,
        *,
        bypass_mutation_block: bool = False,
        expected_type: None = None,
        raise_on_graphql_error: Literal[True] = True,
    ) -> Json.Value: ...

    @staticmethod
    @overload
    def send(
        shop_domain: str,
        access_token: str,
        query: str,
        variables: Json.Object | None = None,
        *,
        bypass_mutation_block: bool = False,
        expected_type: type[_DC],
        raise_on_graphql_error: Literal[True] = True,
    ) -> _DC | None: ...

    @staticmethod
    @overload
    def send(
        shop_domain: str,
        access_token: str,
        query: str,
        variables: Json.Object | None = None,
        *,
        bypass_mutation_block: bool = False,
        expected_type: type[_DC],
        raise_on_graphql_error: Literal[False],
    ) -> tuple[_DC | None, list[str]]: ...

    @staticmethod
    @graphql_rate_limit(
        min_interval_seconds=0.15,
        throttle_cooldown_seconds=0.65,
        max_throttle_retries=12,
    )
    def send(
        shop_domain: str,
        access_token: str,
        query: str,
        variables: Json.Object | None = None,
        *,
        bypass_mutation_block: bool = False,
        expected_type: type[_DC] | None = None,
        raise_on_graphql_error: bool = True,
    ) -> Json.Value | _DC | None | tuple[_DC | None, list[str]]:
        kind = classify_graphql_operation(query)
        if (
            kind == "mutation"
            and not bypass_mutation_block
            and not mutations_allowed_from_g()
        ):
            raise MutationsBlockedError(
                "Mutations are disabled. Turn on the Allow mutations switch in the GraphQL bar."
            )
        resp = requests.post(
            url=f"https://{shop_domain}/admin/api/{Environment.shopify_api_version}/graphql.json",
            headers={
                "X-Shopify-Access-Token": access_token,
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "variables": {
                    k: v for k, v in variables.items() if v is not None
                }
                if variables is not None
                else {},
            },
            timeout=20,
        )
        if resp.status_code == 429:
            ra = resp.headers.get("Retry-After")
            delay: float | None = None
            if ra is not None:
                try:
                    delay = float(ra)
                except ValueError:
                    delay = None
            raise GraphQLThrottled(delay)
        resp.raise_for_status()
        payload = cast(Json.Value, resp.json())
        if isinstance(payload, dict) and is_graphql_throttled_payload(payload):
            raise GraphQLThrottled()
        increment_request_graphql(kind)

        if expected_type is None:
            return payload

        errs = GraphQL.extract_errors(payload)
        data = GraphQL.response_data(payload)

        if raise_on_graphql_error:
            if errs:
                raise RuntimeError("; ".join(errs))
            if data is None:
                raise RuntimeError("GraphQL response missing data.")
            return Utils.dict2dc(data, expected_type)

        if errs:
            return None, errs
        if data is None:
            return None, ["GraphQL response missing data."]
        parsed = Utils.dict2dc(data, expected_type)
        return parsed, []

    @staticmethod
    def subscribe_webhook(
        shop_domain: str,
        access_token: str,
        topic: str,
        uri: str,
    ) -> None:
        """
        webhookSubscriptionCreate — allowed regardless of the mutation allow switch
        (required for app lifecycle, e.g. APP_UNINSTALLED).
        """
        gql: Json.Value = GraphQL.send(
            shop_domain,
            access_token,
            FileLoader.load("webhook_subscription_create.gql"),
            {
                "topic": topic,
                "webhookSubscription": {"uri": uri},
            },
            bypass_mutation_block=True,
        )
        if not isinstance(gql, dict):
            raise RuntimeError("Unexpected GraphQL response for webhook subscription.")
        if errs := GraphQL.extract_errors(gql):
            raise RuntimeError(
                f"GraphQL error creating webhook: {errs!r}"
            )
        data = GraphQL.response_data(gql)
        if data is None:
            raise RuntimeError("GraphQL response missing data.")
        wsc = data.get("webhookSubscriptionCreate")
        if not isinstance(wsc, dict):
            raise RuntimeError("GraphQL response missing webhookSubscriptionCreate.")
        user_errors = wsc.get("userErrors") or []
        if user_errors:
            raise RuntimeError(
                f"webhookSubscriptionCreate userErrors: {user_errors!r}"
            )
        sub = wsc.get("webhookSubscription")
        if not isinstance(sub, dict):
            raise RuntimeError("GraphQL response missing webhookSubscription.")
        sub_id = sub.get("id")
        if not isinstance(sub_id, str):
            raise RuntimeError("Webhook subscription ID is not a string.")
        Database.Webhooks.add_webhook_id(shop_domain, sub_id)
