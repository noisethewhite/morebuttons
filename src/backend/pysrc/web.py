import requests
from typing import cast

from .environment import Environment
from .security import Security
from .routes import Routes
from .graphql import GraphQL
from .web_types import Json


class Web(object):
    @staticmethod
    def subscribe_app_uninstalled_webhook(shop_domain: str, access_token: str) -> None:
        webhook_url = Security.app_public_base_url().rstrip("/") + Routes.APP_UNINSTALLED
        GraphQL.subscribe_webhook(shop_domain, access_token, "APP_UNINSTALLED", webhook_url)

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
                "Accept": "application/json",
            },
            json={
                "client_id": Environment.shopify_api_key,
                "client_secret": Environment.shopify_secret,
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "subject_token": session_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
                "requested_token_type": "urn:shopify:params:oauth:token-type:offline-access-token",
            },
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
