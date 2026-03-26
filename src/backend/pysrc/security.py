import flask
import jwt
import hmac
import hashlib
import base64
import urllib.parse
from .environment import Environment


class Security(object):
    @staticmethod
    def get_session_token() -> str | None:
        auth = flask.request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth.split(" ", 1)[1]

    @staticmethod
    def get_shop_domain(session_token: str) -> str:
        raw = jwt.decode(  # pyright: ignore[reportUnknownMemberType]
            session_token,
            Environment.shopify_secret,
            algorithms=["HS256"],
            audience=Environment.shopify_api_key
        )
        if "dest" not in raw:
            raise RuntimeError("Session token is not a valid JWT.")
        dest = raw["dest"]  # pyright: ignore[reportAny]
        if not isinstance(dest, str):
            raise RuntimeError("Session token destination is not a string.")
        return dest.replace("https://", "").replace("http://", "")

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
