import requests
from .environment import Environment
from typing import TypeAlias, cast
from .database import Database
from .security import Security
from .routes import Routes
from .fileloader import FileLoader


class Json(object):
    String: TypeAlias = str
    Number: TypeAlias = int | float
    Boolean: TypeAlias = bool
    Null: TypeAlias = None
    Array: TypeAlias = list["Json.Value"]
    Object: TypeAlias = dict[String, "Json.Value"]
    Value: TypeAlias = String | Number | Boolean | Null | Array | Object | list[Object]


class Web(object):
    @staticmethod
    def graphql_send(
        shop_domain: str,
        access_token: str,
        query: str,
        variables: Json.Object | None = None
    ) -> Json.Value:
        resp = requests.post(
            url=f"https://{shop_domain}/admin/api/{Environment.shopify_api_version}/graphql.json",
            headers={
                "X-Shopify-Access-Token": access_token,
                "Content-Type": "application/json"
            },
            json={
                "query": query,
                "variables": {
                    k: v for k, v in variables.items() if v is not None
                } if variables is not None else {}
            },
            timeout=20
        )
        resp.raise_for_status()
        return cast(Json.Value, resp.json())

    @staticmethod
    def subscribe_app_uninstalled_webhook(shop_domain: str, access_token: str) -> None:
        webhook_url = Security.app_public_base_url().rstrip("/") + Routes.APP_UNINSTALLED
        gql: Json.Value = Web.graphql_send(
            shop_domain,
            access_token,
            FileLoader.load("webhook_subscription_create.gql"),
            {
                "topic": "APP_UNINSTALLED",
                "webhookSubscription": { "uri": webhook_url },
            },
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

    @staticmethod
    def get_access_token(shop_domain: str, session_token: str) -> str:
        """
        Retrieves the offline access token, which is given
        only once when the app gets installed.
        """
        resp = requests.post(
            f"https://{shop_domain}/admin/oauth/access_token",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
            json={
                "client_id": Environment.shopify_api_key,
                "client_secret": Environment.shopify_secret,
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "subject_token": session_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
                "requested_token_type": "urn:shopify:params:oauth:token-type:offline-access-token"
            }
        )
        resp.raise_for_status()
        data: Json.Value = cast(Json.Value, resp.json())
        if not isinstance(data, dict) or "access_token" not in data:
            raise RuntimeError(
                "Access token was not included in the response from Shopify."
            )
        access_token = data["access_token"]
        if not isinstance(access_token, str):
            raise RuntimeError("Access token is not of type str.")
        return access_token
