import sys
import flask
from werkzeug.wrappers.response import Response
from backend.pysrc.server import Server
from backend.pysrc.web import Web
from backend.pysrc.security import Security
from backend.pysrc.database import Database
from backend.pysrc.environment import Environment
from backend.pysrc.routes import Routes


# ESSENTIAL for Gunicorn to see it.
application = Server.app


CONTENT_SECURITY_POLICY = " ".join([
    "frame-ancestors https://*.myshopify.com https://admin.shopify.com;",
    "script-src 'self' https://unpkg.com https://cdn.shopify.com https://cdn.shopifycloud.com;",
    "style-src 'self' 'unsafe-inline';",
    "img-src 'self' data: https://cdn.shopify.com https://cdn.shopifycdn.net;",
    "connect-src 'self' https://*.myshopify.com https://admin.shopify.com https://cdn.shopify.com https://*.shopifycloud.com https://*.shopifysvc.com;",
    "base-uri 'self';",
    "object-src 'none';",
])


# ---------------------------------------------------------------------------
# Request handling
# ---------------------------------------------------------------------------


@application.before_request
def protect_api() -> None:
    if flask.request.path.startswith(Routes.API):
        Server.session_token = Security.get_session_token()
        Server.shop_domain = Security.get_shop_domain(Server.session_token)

@application.after_request
def set_csp(resp: Response) -> Response:
    resp.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    resp.headers["X-Content-Type-Options"]  = "nosniff"
    _ = resp.headers.pop("X-Frame-Options", None)
    return resp

@application.errorhandler(Exception)
def handle_exception(e: Exception) -> tuple[Response, int]:
    print(str(e), file=sys.stderr)
    return flask.jsonify({ "error": "Internal server error" }), 500


# ---------------------------------------------------------------------------
# Main routes
# ---------------------------------------------------------------------------


@application.route(f"{Routes.WEBHOOKS}/app-uninstalled", methods=["POST"])
def app_uninstalled_webhook():
    if not Security.verify_webhook_hmac():
        return flask.jsonify({ "error": "Unauthorized" }), 401
    shop_domain = flask.request.headers.get("X-Shopify-Shop-Domain", "")
    if not shop_domain:
        return flask.jsonify({ "error": "Missing shop domain" }), 400
    Database.AccessTokens.delete_token(shop_domain)
    Database.Webhooks.delete_row(shop_domain)
    return "", 200


@application.route(f"{Routes.API}/oauth", methods=["POST"])
def oauth():
    if not Database.AccessTokens.get_token(Server.shop_domain):
        access_token = Web.get_access_token(Server.shop_domain, Server.session_token)
        Database.AccessTokens.set_token(Server.shop_domain, access_token)
        Web.subscribe_app_uninstalled_webhook(Server.shop_domain, access_token)
    return flask.jsonify({ "oauthSuccess": True })


@application.route("/")
def index() -> str:
    return flask.render_template(
        "index.html",
        api_key=Environment.shopify_api_key
    )
