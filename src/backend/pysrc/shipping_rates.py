from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, cast

from .fileloader import FileLoader
from .web import Json, Web


def _extract_errors(gql: Json.Value) -> list[str] | None:
    if not isinstance(gql, dict):
        return ["Invalid GraphQL response."]
    errs = gql.get("errors")
    if not isinstance(errs, list) or not errs:
        return None
    out: list[str] = []
    for e in errs:
        if isinstance(e, dict) and isinstance(e.get("message"), str):
            out.append(e["message"])
        else:
            out.append(repr(e))
    return out


def _data(gql: Json.Value) -> dict[str, Any] | None:
    if not isinstance(gql, dict):
        return None
    d = gql.get("data")
    return d if isinstance(d, dict) else None


def _scale_money(amount: str, factor: Decimal) -> str:
    d = Decimal(amount)
    return str((d * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _method_update_input(
    method: dict[str, Any],
    factor: Decimal,
) -> dict[str, Any] | None:
    mid = method.get("id")
    if not isinstance(mid, str):
        return None
    rp = method.get("rateProvider")
    if not isinstance(rp, dict):
        return None
    typename = rp.get("__typename")
    if typename == "DeliveryRateDefinition":
        rid = rp.get("id")
        price = rp.get("price")
        if not isinstance(rid, str) or not isinstance(price, dict):
            return None
        amt = price.get("amount")
        cur = price.get("currencyCode")
        if not isinstance(amt, str) or not isinstance(cur, str):
            return None
        return {
            "id": mid,
            "rateDefinition": {
                "id": rid,
                "price": {
                    "amount": _scale_money(amt, factor),
                    "currencyCode": cur,
                },
            },
        }
    if typename == "DeliveryParticipant":
        pid = rp.get("id")
        ff = rp.get("fixedFee")
        if not isinstance(pid, str) or not isinstance(ff, dict):
            return None
        amt = ff.get("amount")
        cur = ff.get("currencyCode")
        if not isinstance(amt, str) or not isinstance(cur, str):
            return None
        return {
            "id": mid,
            "participant": {
                "id": pid,
                "fixedFee": {
                    "amount": _scale_money(amt, factor),
                    "currencyCode": cur,
                },
            },
        }
    return None


def _chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def collect_methods_and_warnings(
    shop_domain: str,
    access_token: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []

    q_profiles = FileLoader.load("delivery_profiles_page.gql")
    q_zones = FileLoader.load("delivery_profile_group_zones.gql")

    after_profiles: str | None = None
    while True:
        gql = Web.graphql_send(
            shop_domain,
            access_token,
            q_profiles,
            {"first": 50, "after": after_profiles},
        )
        if errs := _extract_errors(gql):
            raise RuntimeError("; ".join(errs))
        data = _data(gql)
        if data is None:
            raise RuntimeError("GraphQL response missing data.")
        conn = data.get("deliveryProfiles")
        if not isinstance(conn, dict):
            break
        edges = conn.get("edges")
        if not isinstance(edges, list):
            break
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node")
            if not isinstance(node, dict):
                continue
            pid = node.get("id")
            pname = node.get("name")
            if not isinstance(pid, str):
                continue
            if not isinstance(pname, str):
                pname = ""
            plgs = node.get("profileLocationGroups")
            if not isinstance(plgs, list):
                continue
            for plg in plgs:
                if not isinstance(plg, dict):
                    continue
                lg = plg.get("locationGroup")
                if not isinstance(lg, dict):
                    continue
                lg_id = lg.get("id")
                if not isinstance(lg_id, str):
                    continue
                _append_zone_methods(
                    shop_domain,
                    access_token,
                    q_zones,
                    pid,
                    pname,
                    lg_id,
                    rows,
                    warnings,
                )

        pi = conn.get("pageInfo")
        if not isinstance(pi, dict) or not pi.get("hasNextPage"):
            break
        ec = pi.get("endCursor")
        if not isinstance(ec, str):
            break
        after_profiles = ec

    return rows, warnings


def _append_zone_methods(
    shop_domain: str,
    access_token: str,
    q_zones: str,
    profile_id: str,
    profile_name: str,
    location_group_id: str,
    rows: list[dict[str, Any]],
    warnings: list[str],
) -> None:
    after_zones: str | None = None
    while True:
        gql = Web.graphql_send(
            shop_domain,
            access_token,
            q_zones,
            {
                "profileId": profile_id,
                "locationGroupId": location_group_id,
                "zonesFirst": 50,
                "zonesAfter": after_zones,
            },
        )
        if errs := _extract_errors(gql):
            raise RuntimeError("; ".join(errs))
        data = _data(gql)
        if data is None:
            raise RuntimeError("GraphQL response missing data.")
        dp = data.get("deliveryProfile")
        if not isinstance(dp, dict):
            break
        plgs = dp.get("profileLocationGroups")
        if not isinstance(plgs, list) or not plgs:
            break
        plg0 = plgs[0]
        if not isinstance(plg0, dict):
            break
        zconn = plg0.get("locationGroupZones")
        if not isinstance(zconn, dict):
            break
        zedges = zconn.get("edges")
        if not isinstance(zedges, list):
            break
        for zedge in zedges:
            if not isinstance(zedge, dict):
                continue
            znode = zedge.get("node")
            if not isinstance(znode, dict):
                continue
            zone = znode.get("zone")
            if not isinstance(zone, dict):
                continue
            zid = zone.get("id")
            zname = zone.get("name")
            if not isinstance(zid, str):
                continue
            if not isinstance(zname, str):
                zname = ""
            md = znode.get("methodDefinitions")
            if not isinstance(md, dict):
                continue
            mpi = md.get("pageInfo")
            if isinstance(mpi, dict) and mpi.get("hasNextPage"):
                warnings.append(
                    f"More than 250 method definitions in a zone; "
                    f"only the first page was loaded (zone {zid})."
                )
            medges = md.get("edges")
            if not isinstance(medges, list):
                continue
            for medge in medges:
                if not isinstance(medge, dict):
                    continue
                mnode = medge.get("node")
                if not isinstance(mnode, dict):
                    continue
                rows.append(
                    {
                        "profileId": profile_id,
                        "profileName": profile_name,
                        "locationGroupId": location_group_id,
                        "zoneId": zid,
                        "zoneName": zname,
                        "method": mnode,
                    }
                )

        pi = zconn.get("pageInfo")
        if not isinstance(pi, dict) or not pi.get("hasNextPage"):
            break
        ec = pi.get("endCursor")
        if not isinstance(ec, str):
            break
        after_zones = ec


def unique_rate_names(rows: list[dict[str, Any]]) -> list[str]:
    names: set[str] = set()
    for row in rows:
        m = row.get("method")
        if not isinstance(m, dict):
            continue
        n = m.get("name")
        if isinstance(n, str) and n:
            names.add(n)
    return sorted(names)


_OPERATOR_SYMBOL: dict[str, str] = {
    "LESS_THAN_OR_EQUAL_TO": "≤",
    "GREATER_THAN_OR_EQUAL_TO": "≥",
    "EQUAL_TO": "=",
    "GREATER_THAN": ">",
    "LESS_THAN": "<",
    "NOT_EQUAL_TO": "≠",
}


def _format_condition(cond: dict[str, Any]) -> str | None:
    op = cond.get("operator")
    crit = cond.get("conditionCriteria")
    if not isinstance(op, str) or not isinstance(crit, dict):
        return None
    typename = crit.get("__typename")
    sym = _OPERATOR_SYMBOL.get(op, op)
    if typename == "Weight":
        unit = crit.get("unit")
        val = crit.get("value")
        if not isinstance(unit, str):
            return None
        if isinstance(val, (int, float)):
            vdisp = val
        elif isinstance(val, str):
            try:
                vdisp = float(val)
            except ValueError:
                return None
        else:
            return None
        return f"Weight {sym} {vdisp} {unit}"
    if typename == "MoneyV2":
        amt = crit.get("amount")
        cur = crit.get("currencyCode")
        if not isinstance(amt, str) or not isinstance(cur, str):
            return None
        return f"Order total {sym} {amt} {cur}"
    return None


def _format_boundary(method: dict[str, Any]) -> str:
    mcs = method.get("methodConditions")
    if not isinstance(mcs, list) or len(mcs) == 0:
        return "No tier limits"
    parts: list[str] = []
    for c in mcs:
        if not isinstance(c, dict):
            continue
        s = _format_condition(c)
        if s:
            parts.append(s)
    if not parts:
        return "Tier conditions"
    return "; ".join(parts)


def _price_pair(method: dict[str, Any], factor: Decimal) -> tuple[str, str] | None:
    rp = method.get("rateProvider")
    if not isinstance(rp, dict):
        return None
    typename = rp.get("__typename")
    if typename == "DeliveryRateDefinition":
        price = rp.get("price")
        if not isinstance(price, dict):
            return None
        amt = price.get("amount")
        cur = price.get("currencyCode")
        if not isinstance(amt, str) or not isinstance(cur, str):
            return None
        new_amt = _scale_money(amt, factor)
        return (f"{amt} {cur}", f"{new_amt} {cur}")
    if typename == "DeliveryParticipant":
        ff = rp.get("fixedFee")
        if not isinstance(ff, dict):
            return None
        amt = ff.get("amount")
        cur = ff.get("currencyCode")
        if not isinstance(amt, str) or not isinstance(cur, str):
            return None
        new_amt = _scale_money(amt, factor)
        return (f"{amt} {cur}", f"{new_amt} {cur}")
    return None


def preview_rate_changes(
    shop_domain: str,
    access_token: str,
    rate_name: str,
    percent: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Returns (profiles, warnings) where each profile has
    id, name, zones: [{ id, name, rows: [{ id, boundary, current, new }] }].
    """
    rows, warnings = collect_methods_and_warnings(shop_domain, access_token)
    factor = Decimal(1) + Decimal(str(percent)) / Decimal(100)

    acc: dict[str, dict[str, Any]] = {}

    for row in rows:
        m = row.get("method")
        if not isinstance(m, dict) or m.get("name") != rate_name:
            continue
        if _method_update_input(cast(dict[str, Any], m), factor) is None:
            continue
        pair = _price_pair(cast(dict[str, Any], m), factor)
        if pair is None:
            continue
        cur_s, new_s = pair
        pid = row.get("profileId")
        zid = row.get("zoneId")
        if not isinstance(pid, str) or not isinstance(zid, str):
            continue
        pname = row.get("profileName")
        zname = row.get("zoneName")
        if not isinstance(pname, str):
            pname = ""
        if not isinstance(zname, str):
            zname = ""
        mid = m.get("id")
        if not isinstance(mid, str):
            continue
        boundary = _format_boundary(cast(dict[str, Any], m))

        if pid not in acc:
            acc[pid] = {"name": pname, "zones": {}}
        zmap = acc[pid]["zones"]
        if not isinstance(zmap, dict):
            continue
        if zid not in zmap:
            zmap[zid] = {"name": zname, "rows": []}
        zent = zmap[zid]
        if not isinstance(zent, dict):
            continue
        rlist = zent.get("rows")
        if not isinstance(rlist, list):
            continue
        rlist.append(
            {
                "id": mid,
                "boundary": boundary,
                "current": cur_s,
                "new": new_s,
            }
        )

    out: list[dict[str, Any]] = []
    for pid in sorted(
        acc.keys(),
        key=lambda i: (str(acc[i].get("name", "")).lower(), i),
    ):
        entry = acc[pid]
        pname = entry.get("name", "")
        if not isinstance(pname, str):
            pname = ""
        zmap = entry.get("zones")
        if not isinstance(zmap, dict):
            continue
        zones_out: list[dict[str, Any]] = []
        for zid in sorted(
            zmap.keys(),
            key=lambda z: (
                str(cast(dict[str, Any], zmap[z]).get("name", "")).lower(),
                z,
            ),
        ):
            zent = zmap[zid]
            if not isinstance(zent, dict):
                continue
            zn = zent.get("name", "")
            if not isinstance(zn, str):
                zn = ""
            rows_list = zent.get("rows")
            if not isinstance(rows_list, list):
                continue
            rows_sorted = sorted(
                rows_list,
                key=lambda r: (
                    str(r.get("boundary", "")),
                    str(r.get("id", "")),
                ),
            )
            zones_out.append(
                {
                    "id": zid,
                    "name": zn,
                    "rows": rows_sorted,
                }
            )
        out.append({"id": pid, "name": pname, "zones": zones_out})

    return out, warnings


def adjust_rates_by_name_percent(
    shop_domain: str,
    access_token: str,
    rate_name: str,
    percent: float,
) -> tuple[int, list[str], list[str]]:
    """
    Returns (updated_method_count, warnings, user_error_messages).
    """
    rows, warnings = collect_methods_and_warnings(shop_domain, access_token)
    factor = Decimal(1) + Decimal(str(percent)) / Decimal(100)

    by_profile: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )

    updated = 0
    for row in rows:
        m = row.get("method")
        if not isinstance(m, dict):
            continue
        if m.get("name") != rate_name:
            continue
        inp = _method_update_input(cast(dict[str, Any], m), factor)
        if inp is None:
            warnings.append(
                f"Skipped a rate named {rate_name!r} (unsupported rate type or missing price)."
            )
            continue
        pid = row["profileId"]
        lg = row["locationGroupId"]
        zid = row["zoneId"]
        by_profile[pid][lg][zid].append(inp)
        updated += 1

    if updated == 0:
        return 0, warnings, ["No matching adjustable rates found for that name."]

    mut = FileLoader.load("delivery_profile_update.gql")
    user_msgs: list[str] = []

    for profile_id, by_lg in by_profile.items():
        for lg_id, by_zone in by_lg.items():
            zones_payload: list[dict[str, Any]] = []
            for zone_id, methods in by_zone.items():
                zones_payload.append(
                    {"id": zone_id, "methodDefinitionsToUpdate": methods}
                )
            for chunk in _chunks(zones_payload, 5):
                gql = Web.graphql_send(
                    shop_domain,
                    access_token,
                    mut,
                    {
                        "id": profile_id,
                        "profile": {
                            "locationGroupsToUpdate": [
                                {"id": lg_id, "zonesToUpdate": chunk}
                            ]
                        },
                    },
                )
                if errs := _extract_errors(gql):
                    user_msgs.extend(errs)
                    continue
                data = _data(gql)
                if data is None:
                    user_msgs.append("GraphQL response missing data.")
                    continue
                dpu = data.get("deliveryProfileUpdate")
                if not isinstance(dpu, dict):
                    continue
                ues = dpu.get("userErrors")
                if isinstance(ues, list):
                    for ue in ues:
                        if isinstance(ue, dict) and isinstance(ue.get("message"), str):
                            user_msgs.append(ue["message"])

    return updated, warnings, user_msgs
