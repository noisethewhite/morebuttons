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
from backend.pysrc.catalog_cache import get_shipping_catalog
from backend.pysrc.product_tag_pricing import (
    apply_variant_price_changes,
    create_tagged_product_job,
    delete_tagged_product_job,
    fetch_product_tag_strings,
    preview_variant_price_changes,
    take_tagged_product_job,
)
from backend.pysrc.shipping_catalog_job import (
    create_shipping_catalog_job,
    delete_shipping_catalog_job,
    take_shipping_catalog_job,
)
from backend.pysrc.shipping_rates import (
    adjust_rates_by_name_percent,
    preview_rate_changes
)
from backend.pysrc.order_carrier_job import (
    create_order_carrier_job,
    delete_order_carrier_job,
    take_order_carrier_job,
)
from backend.pysrc.order_lookup import lookup_order_by_tracking


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
    flask.g.graphql_phase_total = None
    flask.g.graphql_phase_done = None


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
    pt = getattr(flask.g, "graphql_phase_total", None)
    pd = getattr(flask.g, "graphql_phase_done", None)
    if isinstance(pt, (int, float)):
        resp.headers["X-GraphQL-Phase-Total"] = str(int(pt))
    if isinstance(pd, (int, float)):
        resp.headers["X-GraphQL-Phase-Done"] = str(int(pd))
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


@application.route(Routes.SHIPPING_CATALOG_START, methods=["POST"])
def shipping_catalog_start():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({ "error": "Not installed" }), 401
    jid = create_shipping_catalog_job(Server.shop_domain, token)
    return flask.jsonify({ "jobId": jid })


@application.route(Routes.SHIPPING_CATALOG_STEP, methods=["POST"])
def shipping_catalog_step():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({ "error": "Not installed" }), 401
    raw_body = cast(Json.Value, flask.request.get_json(silent=True))
    body = raw_body if isinstance(raw_body, dict) else {}
    job_id = body.get("jobId")
    if not isinstance(job_id, str) or not job_id.strip():
        return flask.jsonify({ "error": "Missing jobId" }), 400
    job = take_shipping_catalog_job(job_id.strip())
    if job is None:
        return flask.jsonify({ "error": "Unknown or expired job" }), 404
    try:
        result = job.step()
    except RuntimeError as e:
        return flask.jsonify({ "error": str(e) }), 502
    flask.g.graphql_phase_total = result.get("total")
    flask.g.graphql_phase_done = result.get("completed")
    if result.get("done"):
        delete_shipping_catalog_job(job_id.strip())
    return flask.jsonify(result)


@application.route(Routes.SHIPPING_RATE_NAMES, methods=["GET"])
def shipping_rate_names():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({ "error": "Not installed" }), 401
    cached = get_shipping_catalog(Server.shop_domain)
    if cached is None:
        return flask.jsonify({
            "error": "Shipping catalog not loaded. Wait for loading to finish.",
        }), 400
    rows, warnings = cached
    filters = rows.build_delivery_profile_filters()
    return flask.jsonify({
        "names": rows.unique_rate_names(),
        **filters.to_json(),
        "warnings": warnings,
    })


@application.route(Routes.PRODUCT_TAGS, methods=["GET"])
def product_tags_list():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({ "error": "Not installed" }), 401
    try:
        tags = fetch_product_tag_strings(Server.shop_domain, token)
        return flask.jsonify({ "tags": tags })
    except RuntimeError as e:
        return flask.jsonify({ "error": str(e) }), 502


@application.route(Routes.PRODUCT_TAG_CATALOG_START, methods=["POST"])
def product_tag_catalog_start():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({ "error": "Not installed" }), 401
    raw_body = cast(Json.Value, flask.request.get_json(silent=True))
    body = raw_body if isinstance(raw_body, dict) else {}
    tag_raw = body.get("tag")
    tag = tag_raw.strip() if isinstance(tag_raw, str) else ""
    if not tag:
        return flask.jsonify({ "error": "Missing tag" }), 400
    jid = create_tagged_product_job(Server.shop_domain, token, tag)
    return flask.jsonify({ "jobId": jid })


@application.route(Routes.PRODUCT_TAG_CATALOG_STEP, methods=["POST"])
def product_tag_catalog_step():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({ "error": "Not installed" }), 401
    raw_body = cast(Json.Value, flask.request.get_json(silent=True))
    body = raw_body if isinstance(raw_body, dict) else {}
    job_id = body.get("jobId")
    if not isinstance(job_id, str) or not job_id.strip():
        return flask.jsonify({ "error": "Missing jobId" }), 400
    job = take_tagged_product_job(job_id.strip())
    if job is None:
        return flask.jsonify({ "error": "Unknown or expired job" }), 404
    try:
        result = job.step()
    except RuntimeError as e:
        return flask.jsonify({ "error": str(e) }), 502
    flask.g.graphql_phase_total = result.total
    flask.g.graphql_phase_done = result.completed
    if result.done:
        delete_tagged_product_job(job_id.strip())
    return flask.jsonify(result.to_json())


@application.route(Routes.PRODUCT_TAG_PRICING_PREVIEW, methods=["GET"])
def product_tag_pricing_preview():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({ "error": "Not installed" }), 401
    tag = flask.request.args.get("tag", "").strip()
    if not tag:
        return flask.jsonify({ "error": "Missing tag" }), 400
    percent_raw = flask.request.args.get("percent", "")
    try:
        percent = float(percent_raw.strip())
    except (TypeError, ValueError):
        return flask.jsonify({ "error": "Invalid percent" }), 400
    mode_raw = flask.request.args.get("mode", "").strip().lower()
    adjustment_mode: Literal["percent", "offset"] = (
        "offset"
        if mode_raw in ("offset", "absolute")
        else "percent"
    )
    try:
        profiles, warnings = preview_variant_price_changes(
            Server.shop_domain,
            tag,
            percent,
            adjustment_mode,
        )
        return flask.jsonify({
            "profiles": [asdict(p) for p in profiles],
            "warnings": warnings,
        })
    except RuntimeError as e:
        return flask.jsonify({ "error": str(e) }), 400


@application.route(Routes.PRODUCT_TAG_PRICING_ADJUST, methods=["POST"])
def product_tag_pricing_adjust():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({ "error": "Not installed" }), 401
    raw_body = cast(Json.Value, flask.request.get_json(silent=True))
    body = raw_body if isinstance(raw_body, dict) else {}
    tag_raw = body.get("tag")
    percent_raw = body.get("percent")
    tag = tag_raw.strip() if isinstance(tag_raw, str) else ""
    if not tag:
        return flask.jsonify({ "error": "Missing tag" }), 400
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
    mode_body = body.get("mode")
    adjustment_mode_post: Literal["percent", "offset"] = (
        "offset"
        if isinstance(mode_body, str)
        and mode_body.strip().lower() in ("offset", "absolute")
        else "percent"
    )
    try:
        updated, warnings, user_msgs = apply_variant_price_changes(
            Server.shop_domain,
            token,
            tag,
            percent,
            adjustment_mode_post,
        )
        return flask.jsonify({
            "updated": updated,
            "warnings": warnings,
            "userErrors": user_msgs,
        })
    except RuntimeError as e:
        return flask.jsonify({ "error": str(e) }), 400


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


@application.route(Routes.ORDER_CARRIER_CATALOG_START, methods=["POST"])
def order_carrier_catalog_start():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({"error": "Not installed"}), 401
    raw_body = cast(Json.Value, flask.request.get_json(silent=True))
    body = raw_body if isinstance(raw_body, dict) else {}
    date_from_raw = body.get("dateFrom")
    date_to_raw = body.get("dateTo")
    max_orders_raw = body.get("maxOrders", 1000)
    date_from = (
        date_from_raw.strip()
        if isinstance(date_from_raw, str) and date_from_raw.strip()
        else None
    )
    date_to = (
        date_to_raw.strip()
        if isinstance(date_to_raw, str) and date_to_raw.strip()
        else None
    )
    try:
        max_orders = max(1, min(10000, int(max_orders_raw)))
    except (TypeError, ValueError):
        max_orders = 1000
    jid = create_order_carrier_job(Server.shop_domain, token, max_orders, date_from, date_to)
    return flask.jsonify({"jobId": jid})


@application.route(Routes.ORDER_CARRIER_CATALOG_STEP, methods=["POST"])
def order_carrier_catalog_step():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({"error": "Not installed"}), 401
    raw_body = cast(Json.Value, flask.request.get_json(silent=True))
    body = raw_body if isinstance(raw_body, dict) else {}
    job_id = body.get("jobId")
    if not isinstance(job_id, str) or not job_id.strip():
        return flask.jsonify({"error": "Missing jobId"}), 400
    job = take_order_carrier_job(job_id.strip())
    if job is None:
        return flask.jsonify({"error": "Unknown or expired job"}), 404
    try:
        result = job.step()
    except RuntimeError as e:
        return flask.jsonify({"error": str(e)}), 502
    flask.g.graphql_phase_total = result.total
    flask.g.graphql_phase_done = result.completed
    if result.done:
        delete_order_carrier_job(job_id.strip())
    return flask.jsonify(result.to_json())


@application.route(Routes.ORDER_BY_TRACKING, methods=["GET"])
def order_by_tracking():
    token = Database.AccessTokens.get_token(Server.shop_domain)
    if not token:
        return flask.jsonify({"error": "Not installed"}), 401
    tracking_number = flask.request.args.get("trackingNumber", "").strip()
    if not tracking_number:
        return flask.jsonify({"error": "Missing trackingNumber"}), 400
    carrier_raw = flask.request.args.get("carrier", "").strip()
    carrier = carrier_raw if carrier_raw else None
    date_from = flask.request.args.get("dateFrom", "").strip() or None
    date_to = flask.request.args.get("dateTo", "").strip() or None
    try:
        max_orders = max(1, min(10000, int(flask.request.args.get("maxOrders", "250"))))
    except (TypeError, ValueError):
        max_orders = 250
    try:
        results, warnings = lookup_order_by_tracking(
            Server.shop_domain, token, tracking_number, carrier,
            date_from=date_from, date_to=date_to, max_orders=max_orders,
        )
        return flask.jsonify({
            "orders": [r.to_json() for r in results],
            "warnings": warnings,
        })
    except RuntimeError as e:
        return flask.jsonify({"error": str(e)}), 502


@application.route("/")
def index() -> str:
    return flask.render_template(
        "index.html",
        api_key=Environment.shopify_api_key
    )
