import sys
from dataclasses import asdict
from typing import Literal, cast
from backend.pysrc.web_types import Json
import flask
from werkzeug.wrappers.response import Response
from backend.pysrc.server import Server
from backend.pysrc.graphql import MutationsBlockedError
from backend.pysrc.web import Web
from backend.pysrc.security import Security
from backend.pysrc.database import Database
from backend.pysrc.environment import Environment
from backend.pysrc.routes import Routes
from backend.pysrc.shipping_rates import (
    adjust_rates_by_name_percent,
    build_delivery_profile_filters,
    collect_methods_and_warnings,
    preview_rate_changes,
    unique_rate_names,
)


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
def init_graphql_request_g() -> None:
    flask.g.graphql_queries = 0
    flask.g.graphql_mutations = 0
    flask.g.allow_graphql_mutations = False


@application.before_request
def protect_api() -> None:
    if flask.request.path.startswith(Routes.API):
        Server.session_token = Security.get_session_token()
        Server.shop_domain = Security.get_shop_domain(Server.session_token)


@application.before_request
def sync_mutation_allow_to_g() -> None:
    if not flask.request.path.startswith(Routes.API):
        return
    sd = Server.shop_domain
    if not sd:
        return
    flask.g.allow_graphql_mutations = Database.MutationAllow.get_allow(sd)

@application.after_request
def set_csp(resp: Response) -> Response:
    resp.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    resp.headers["X-Content-Type-Options"]  = "nosniff"
    _ = resp.headers.pop("X-Frame-Options", None)
    return resp


@application.after_request
def add_graphql_request_count_headers(resp: Response) -> Response:
    q = int(getattr(flask.g, "graphql_queries", 0))
    m = int(getattr(flask.g, "graphql_mutations", 0))
    resp.headers["X-GraphQL-Queries-Request"] = str(q)
    resp.headers["X-GraphQL-Mutations-Request"] = str(m)
    return resp

@application.errorhandler(Exception)
def handle_exception(e: Exception) -> tuple[Response, int]:
    if isinstance(e, MutationsBlockedError):
        return flask.jsonify({ "error": str(e), "code": "MUTATIONS_BLOCKED" }), 403
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


@application.route(Routes.SHIPPING_RATE_NAMES, methods=["GET"])
def shipping_rate_names():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({ "error": "Not installed" }), 401
    try:
        rows, warnings = collect_methods_and_warnings(Server.shop_domain, token)
        names = unique_rate_names(rows)
        profiles, zones_by_profile = build_delivery_profile_filters(rows)
        return flask.jsonify({
            "names": names,
            "profiles": profiles,
            "zonesByProfile": zones_by_profile,
            "warnings": warnings,
        })
    except RuntimeError as e:
        return flask.jsonify({ "error": str(e) }), 502


@application.route(Routes.SHIPPING_RATES_PREVIEW, methods=["GET"])
def shipping_rates_preview():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({ "error": "Not installed" }), 401
    name = flask.request.args.get("name", "")
    percent_raw = flask.request.args.get("percent", "")
    if not name.strip():
        return flask.jsonify({ "error": "Missing or invalid name" }), 400
    try:
        percent = float(percent_raw.strip())
    except (TypeError, ValueError):
        return flask.jsonify({ "error": "Invalid percent" }), 400
    profile_id = flask.request.args.get("profileId", "").strip() or None
    zone_id = flask.request.args.get("zoneId", "").strip() or None
    mode_raw = flask.request.args.get("mode", "").strip().lower()
    adjustment_mode: Literal["percent", "offset"] = (
        "offset"
        if mode_raw in ("offset", "absolute")
        else "percent"
    )
    try:
        profiles, warnings = preview_rate_changes(
            Server.shop_domain,
            token,
            name.strip(),
            percent,
            profile_id,
            zone_id,
            adjustment_mode,
        )
        return flask.jsonify({
            "profiles": [asdict(p) for p in profiles],
            "warnings": warnings,
        })
    except RuntimeError as e:
        return flask.jsonify({ "error": str(e) }), 502


@application.route(Routes.SHIPPING_RATES_ADJUST, methods=["POST"])
def shipping_rates_adjust():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({ "error": "Not installed" }), 401
    raw_body = cast(Json.Value, flask.request.get_json(silent=True))
    body = raw_body if isinstance(raw_body, dict) else {}
    name = body.get("name")
    percent_raw = body.get("percent")
    if not isinstance(name, str) or not name.strip():
        return flask.jsonify({ "error": "Missing or invalid name" }), 400
    if isinstance(percent_raw, bool) or percent_raw is None:
        return flask.jsonify({ "error": "Invalid percent" }), 400
    if isinstance(percent_raw, (int, float)):
        percent = float(percent_raw)
    elif isinstance(percent_raw, str):
        try:
            percent = float(percent_raw.strip())
        except ValueError:
            return flask.jsonify({ "error": "Invalid percent" }), 400
    else:
        return flask.jsonify({ "error": "Invalid percent" }), 400
    profile_id_raw = body.get("profileId")
    zone_id_raw = body.get("zoneId")
    profile_id = (
        profile_id_raw.strip()
        if isinstance(profile_id_raw, str) and profile_id_raw.strip()
        else None
    )
    zone_id = (
        zone_id_raw.strip()
        if isinstance(zone_id_raw, str) and zone_id_raw.strip()
        else None
    )
    mode_body = body.get("mode")
    adjustment_mode_post: Literal["percent", "offset"] = (
        "offset"
        if isinstance(mode_body, str)
        and mode_body.strip().lower() in ("offset", "absolute")
        else "percent"
    )
    try:
        updated, warnings, user_errors = adjust_rates_by_name_percent(
            Server.shop_domain,
            token,
            name.strip(),
            percent,
            profile_id,
            zone_id,
            adjustment_mode_post,
        )
        return flask.jsonify({
            "updated": updated,
            "warnings": warnings,
            "userErrors": user_errors,
        })
    except RuntimeError as e:
        return flask.jsonify({ "error": str(e) }), 502


@application.route(Routes.GRAPHQL_MUTATION_ALLOW, methods=["GET", "POST"])
def graphql_mutation_allow():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({ "error": "Not installed" }), 401
    if flask.request.method == "GET":
        return flask.jsonify({
            "allowMutations": Database.MutationAllow.get_allow(Server.shop_domain),
        })
    raw_body = cast(Json.Value, flask.request.get_json(silent=True))
    body = raw_body if isinstance(raw_body, dict) else {}
    am = body.get("allowMutations")
    if isinstance(am, bool):
        allow = am
    elif isinstance(am, str) and am.lower() in ("true", "false"):
        allow = am.lower() == "true"
    else:
        return flask.jsonify({ "error": "allowMutations must be a boolean" }), 400
    Database.MutationAllow.set_allow(Server.shop_domain, allow)
    flask.g.allow_graphql_mutations = allow
    return flask.jsonify({ "allowMutations": allow })


@application.route("/")
def index() -> str:
    return flask.render_template(
        "index.html",
        api_key=Environment.shopify_api_key
    )
