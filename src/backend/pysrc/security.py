import flask
import jwt
import hmac
import hashlib
import base64
import urllib.parse
import requests
from .environment import Environment
from .strict_json import Json
from .graphql import GraphQL
from .database import Database


_WEBHOOK_SUBSCRIPTION_CREATE = """
mutation webhookSubscriptionCreate(
  $topic: WebhookSubscriptionTopic!,
  $webhookSubscription: WebhookSubscriptionInput!
) {
  webhookSubscriptionCreate(
    topic: $topic,
    webhookSubscription: $webhookSubscription
  ) {
    webhookSubscription { id topic uri }
    userErrors { field message }
  }
}
"""

APP_UNINSTALLED_WEBHOOK_PATH = "/webhooks/app-uninstalled"


class Security(object):
    @staticmethod
    def get_session_token() -> str | None:
        auth = flask.request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth.split(" ", 1)[1]

    @staticmethod
    def get_shop_domain(session_token: str) -> str:
        return jwt.decode( # pyright: ignore[reportUnknownMemberType]
            session_token,
            Environment.shopify_secret,
            algorithms=["HS256"],
            audience=Environment.shopify_api_key
        )["dest"].replace("https://", "").replace("http://", "")

    @staticmethod
    def verify_oauth_hmac() -> bool:
        query_string = urllib.parse.parse_qs(
            flask.request.query_string.decode("utf-8"),
            keep_blank_values=True
        )
        digest_a = hmac.new(
            Environment.shopify_secret.encode(),
            urllib.parse.urlencode(
                sorted(
                    [(k, v[0]) for k, v in query_string.items() if k != "hmac"],
                    key=lambda x: x[0]
                ),
                doseq=False
            ).encode(),
            hashlib.sha256
        ).hexdigest()
        digest_b = query_string.get("hmac", [""])[0]
        return hmac.compare_digest(digest_a, digest_b)

    @staticmethod
    def verify_webhook_hmac() -> bool:
        digest_a = base64.b64encode(
            hmac.new(
                Environment.shopify_secret.encode(),
                flask.request.get_data(),
                hashlib.sha256
            ).digest()
        ).decode()
        digest_b = flask.request.headers.get('X-Shopify-Hmac-Sha256', '')
        return hmac.compare_digest(digest_a, digest_b)

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
        data: Json.Value = resp.json()
        if not isinstance(data, dict) or "access_token" not in data:
            raise RuntimeError(
                "Access token was not included in the response from Shopify."
            )
        access_token = data["access_token"]
        if not isinstance(access_token, str):
            raise RuntimeError("Access token is not of type str.")
        return access_token

    @staticmethod
    def app_public_base_url() -> str:
        """
        Origin for URLs Shopify must call (webhooks). Prefer SHOPIFY_APP_URL, then
        X-Forwarded-* / ProxyFix, then request.url_root.
        """
        explicit = Environment.public_app_url.rstrip("/")
        if explicit:
            return explicit
        req = flask.request
        proto = req.headers.get("X-Forwarded-Proto", req.scheme)
        host = req.headers.get("X-Forwarded-Host", req.host)
        return f"{proto}://{host}".rstrip("/")

    @staticmethod
    def subscribe_app_uninstalled_webhook(shop_domain: str, access_token: str) -> None:
        webhook_url = Security.app_public_base_url().rstrip("/") + APP_UNINSTALLED_WEBHOOK_PATH
        gql: Json.Value = GraphQL.send(
            shop_domain,
            access_token,
            _WEBHOOK_SUBSCRIPTION_CREATE,
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
        if isinstance(sub, dict) and isinstance(sub.get("id"), str):
            Database.Webhooks.add_webhook_id(shop_domain, sub["id"])
