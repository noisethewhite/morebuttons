import requests
import flask
from flask import has_request_context
from typing import cast

from .environment import Environment
from .database import Database
from .fileloader import FileLoader
from .graphql_counters import classify_graphql_operation, increment_request_graphql
from .rate_limiter import GraphQLThrottled, graphql_rate_limit, is_graphql_throttled_payload
from .web_types import Json


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
    ) -> Json.Value:
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
        return payload

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
        if gql.get("errors"):
            raise RuntimeError(
                f"GraphQL error creating webhook: {gql['errors']!r}"
            )
        data = gql.get("data")
        if not isinstance(data, dict):
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
