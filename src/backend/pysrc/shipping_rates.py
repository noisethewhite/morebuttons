from __future__ import annotations
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, cast
from .fileloader import FileLoader
from .graphql import GraphQL
from .web_types import Json
from .symbols import Currency, ComparisonSymbol


# Cap methodDefinitionsToUpdate per deliveryProfileUpdate mutation (total across zones in
# that mutation). Avoids oversized payloads, timeouts, and Shopify input limits.
_MAX_DELIVERY_METHOD_UPDATES_PER_MUTATION = 25


def _extract_errors(gql: Json.Value) -> list[str] | None:
    if not isinstance(gql, dict):
        return ["Invalid GraphQL response."]
    errs = gql.get("errors")
    if not isinstance(errs, list) or not errs:
        return None
    out: list[str] = []
    for e in errs:
        if isinstance(e, dict):
            msg = e.get("message")
            if isinstance(msg, str):
                out.append(msg)
        else:
            out.append(repr(e))
    return out


def _data(gql: Json.Value) -> Json.Object | None:
    if not isinstance(gql, dict):
        return None
    d = gql.get("data")
    return d if isinstance(d, dict) else None


def _scale_money(amount: str, factor: Decimal) -> str:
    d = Decimal(amount)
    return str((d * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _offset_money(amount: str, delta: Decimal) -> str:
    d = Decimal(amount) + delta
    if d < 0:
        d = Decimal(0)
    return str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _method_update_input(
    method: Json.Object,
    factor: Decimal,
) -> Json.Object | None:
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


def _method_update_input_offset(
    method: Json.Object,
    delta: Decimal,
) -> Json.Object | None:
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
        new_amt = _offset_money(amt, delta)
        return {
            "id": mid,
            "rateDefinition": {
                "id": rid,
                "price": {
                    "amount": new_amt,
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
        new_amt = _offset_money(amt, delta)
        return {
            "id": mid,
            "participant": {
                "id": pid,
                "fixedFee": {
                    "amount": new_amt,
                    "currencyCode": cur,
                },
            },
        }
    return None


def _chunks(items: list[Json.Object], size: int) -> list[list[Json.Object]]:
    return [items[i : i + size] for i in range(0, len(items), size)]




def _zone_method_update_batches(
    by_zone: dict[str, list[Json.Object]],
    max_method_updates_per_mutation: int,
) -> list[list[Json.Object]]:
    """
    Split zone → method update inputs into several GraphQL mutations.

    Each zone's list is split into slices of at most ``max_method_updates_per_mutation``,
    then slices are packed into batches so each batch has at most that many updates total
    (multiple zones may share one mutation when they fit).
    """
    pieces: list[tuple[str, list[Json.Value]]] = []
    for zone_id, methods in by_zone.items():
        for chunk in _chunks(methods, max_method_updates_per_mutation):
            pieces.append((zone_id, cast(list[Json.Value], chunk)))
    batches: list[list[Json.Object]] = []
    cur: list[Json.Object] = []
    cur_total = 0
    for zid, mets in pieces:
        n = len(mets)
        if cur_total + n > max_method_updates_per_mutation and cur:
            batches.append(cur)
            cur = []
            cur_total = 0
        cur.append(
            {
                "id": zid,
                "methodDefinitionsToUpdate": mets,
            }
        )
        cur_total += n
    if cur:
        batches.append(cur)
    return batches


def collect_methods_and_warnings(
    shop_domain: str,
    access_token: str,
) -> tuple[list[Json.Object], list[str]]:
    warnings: list[str] = []
    rows: list[Json.Object] = []

    q_profiles = FileLoader.load("delivery_profiles_page.gql")
    q_zones = FileLoader.load("delivery_profile_group_zones.gql")

    after_profiles: str | None = None
    while True:
        gql = GraphQL.send(
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
    rows: list[Json.Object],
    warnings: list[str],
) -> None:
    after_zones: str | None = None
    while True:
        gql = GraphQL.send(
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
                    f"More than 250 method definitions in a zone; " + \
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


def unique_rate_names(rows: list[Json.Object]) -> list[str]:
    names: set[str] = set()
    for row in rows:
        m = row.get("method")
        if not isinstance(m, dict):
            continue
        n = m.get("name")
        if isinstance(n, str) and n:
            names.add(n)
    return sorted(names)


def build_delivery_profile_filters(
    rows: list[Json.Object],
) -> tuple[list[Json.Object], Json.Object]:
    """Unique delivery profiles and zones per profile (for filter dropdowns)."""
    profiles_map: dict[str, str] = {}
    zones_by_profile: dict[str, dict[str, str]] = defaultdict(dict)
    for row in rows:
        pid = row.get("profileId")
        pname = row.get("profileName")
        zid = row.get("zoneId")
        zname = row.get("zoneName")
        if isinstance(pid, str) and isinstance(pname, str):
            profiles_map[pid] = pname
        if isinstance(pid, str) and isinstance(zid, str) and isinstance(zname, str):
            zones_by_profile[pid][zid] = zname
    profiles = [
        {"id": k, "name": v}
        for k, v in sorted(profiles_map.items(), key=lambda x: (x[1].lower(), x[0]))
    ]
    zones_out: Json.Object = {}
    for pid in sorted(zones_by_profile.keys()):
        zd = zones_by_profile[pid]
        zones_list = [
            {"id": zid, "name": zd[zid]}
            for zid in sorted(zd.keys(), key=lambda z: (zd[z].lower(), z))
        ]
        zones_out[pid] = cast(list[Json.Value], zones_list)
    return cast(list[Json.Object], profiles), zones_out


def _row_matches_profile_zone(
    row: Json.Object,
    profile_id: str | None,
    zone_id: str | None,
) -> bool:
    if profile_id is not None:
        if row.get("profileId") != profile_id:
            return False
    if zone_id is not None:
        if row.get("zoneId") != zone_id:
            return False
    return True


def _fmt_weight_num(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    s = f"{v:.6f}".rstrip("0").rstrip(".")
    return s


_WEIGHT_UNIT_LABEL: dict[str, str] = {
    "KILOGRAMS": "kg",
    "GRAMS": "g",
    "POUNDS": "lb",
    "OUNCES": "oz",
}


def _weight_unit_label(unit: str) -> str:
    return _WEIGHT_UNIT_LABEL.get(unit, unit.lower())


def _parse_weight_triple(cond: Json.Object) -> tuple[str, float, str] | None:
    crit = cond.get("conditionCriteria")
    op = cond.get("operator")
    if not isinstance(crit, dict) or crit.get("__typename") != "Weight":
        return None
    if not isinstance(op, str):
        return None
    unit = crit.get("unit")
    val = crit.get("value")
    if not isinstance(unit, str):
        return None
    if isinstance(val, (int, float)):
        vdisp = float(val)
    elif isinstance(val, str):
        try:
            vdisp = float(val)
        except ValueError:
            return None
    else:
        return None
    return (op, vdisp, unit)


def _parse_money_triple(cond: Json.Object) -> tuple[str, str, str] | None:
    crit = cond.get("conditionCriteria")
    op = cond.get("operator")
    if not isinstance(crit, dict) or crit.get("__typename") != "MoneyV2":
        return None
    if not isinstance(op, str):
        return None
    amt = crit.get("amount")
    cur = crit.get("currencyCode")
    if not isinstance(amt, str) or not isinstance(cur, str):
        return None
    return (op, amt, cur.upper())


def _format_weight_segment(conds: list[Json.Object]) -> str | None:
    parsed: list[tuple[str, float, str]] = []
    for c in conds:
        p = _parse_weight_triple(c)
        if p:
            parsed.append(p)
    if not parsed:
        return None
    units = {u for _, _, u in parsed}
    if len(units) != 1:
        return "; ".join(
            s
            for c in conds
            if (s := _format_condition(c)) is not None
        ) or None
    unit = next(iter(units))
    label = _weight_unit_label(unit)
    low_ops = frozenset({"GREATER_THAN_OR_EQUAL_TO", "GREATER_THAN"})
    high_ops = frozenset({"LESS_THAN_OR_EQUAL_TO", "LESS_THAN"})
    lows = [v for op, v, _ in parsed if op in low_ops]
    highs = [v for op, v, _ in parsed if op in high_ops]
    eqs = [v for op, v, _ in parsed if op == "EQUAL_TO"]

    if len(parsed) == 1:
        op, v, _u = parsed[0]
        if op in low_ops:
            return f"Weight: ≥{_fmt_weight_num(v)} {label}"
        if op in high_ops:
            return f"Weight: ≤{_fmt_weight_num(v)} {label}"
        if op == "EQUAL_TO":
            return f"Weight: {_fmt_weight_num(v)} {label}"

    if lows and highs:
        lo = max(lows)
        hi = min(highs)
        if lo <= hi:
            return f"Weight: {_fmt_weight_num(lo)}–{_fmt_weight_num(hi)} {label}"

    if lows and not highs:
        return f"Weight: ≥{_fmt_weight_num(max(lows))} {label}"
    if highs and not lows:
        return f"Weight: ≤{_fmt_weight_num(min(highs))} {label}"
    if eqs and len(eqs) == 1 and not lows and not highs:
        return f"Weight: {_fmt_weight_num(eqs[0])} {label}"
    return None


def _format_money_segment(conds: list[Json.Object]) -> str | None:
    parsed: list[tuple[str, str, str]] = []
    for c in conds:
        p = _parse_money_triple(c)
        if p:
            parsed.append(p)
    if not parsed:
        return None
    currencies = {c for _, _, c in parsed}
    if len(currencies) != 1:
        return "; ".join(
            s
            for c in conds
            if (s := _format_condition(c)) is not None
        ) or None
    cur = next(iter(currencies))
    low_ops = frozenset({"GREATER_THAN_OR_EQUAL_TO", "GREATER_THAN"})
    high_ops = frozenset({"LESS_THAN_OR_EQUAL_TO", "LESS_THAN"})
    lows = [(a, c) for op, a, c in parsed if op in low_ops]
    highs = [(a, c) for op, a, c in parsed if op in high_ops]
    eqs = [a for op, a, _ in parsed if op == "EQUAL_TO"]

    if len(parsed) == 1:
        op, amt, c = parsed[0]
        sym = ComparisonSymbol.get(op)
        disp = Currency.format_amount(amt, c)
        if op == "EQUAL_TO":
            return f"Order total: {disp}"
        return f"Order total: {sym} {disp}"

    if lows and highs:
        lo_amt = max(Decimal(a) for a, _c in lows)
        hi_amt = min(Decimal(a) for a, _c in highs)
        if lo_amt <= hi_amt:
            return Currency.format_range(str(lo_amt), str(hi_amt), cur)

    if lows and not highs:
        best = max(Decimal(a) for a, _c in lows)
        disp = Currency.format_amount(str(best), cur)
        return f"Order total: ≥ {disp}"
    if highs and not lows:
        best = min(Decimal(a) for a, _c in highs)
        disp = Currency.format_amount(str(best), cur)
        return f"Order total: ≤ {disp}"
    if len(eqs) == 1 and not lows and not highs:
        return f"Order total: {Currency.format_amount(eqs[0], cur)}"
    return None


def _format_condition(cond: Json.Object) -> str | None:
    op = cond.get("operator")
    crit = cond.get("conditionCriteria")
    if not isinstance(op, str) or not isinstance(crit, dict):
        return None
    typename = crit.get("__typename")
    sym = ComparisonSymbol.get(op)
    if typename == "Weight":
        unit = crit.get("unit")
        val = crit.get("value")
        if not isinstance(unit, str):
            return None
        if isinstance(val, (int, float)):
            vdisp = float(val)
        elif isinstance(val, str):
            try:
                vdisp = float(val)
            except ValueError:
                return None
        else:
            return None
        ul = _weight_unit_label(unit)
        return f"Weight: {sym} {_fmt_weight_num(vdisp)} {ul}"
    if typename == "MoneyV2":
        amt = crit.get("amount")
        cur = crit.get("currencyCode")
        if not isinstance(amt, str) or not isinstance(cur, str):
            return None
        disp = Currency.format_amount(amt, cur)
        return f"Order total: {sym} {disp}"
    return None


def _format_boundary(method: Json.Object) -> str:
    mcs = method.get("methodConditions")
    if not isinstance(mcs, list) or len(mcs) == 0:
        return "No tier limits"
    weight_conds = [
        c for c in mcs if isinstance(c, dict) and _parse_weight_triple(c) is not None
    ]
    money_conds = [
        c for c in mcs if isinstance(c, dict) and _parse_money_triple(c) is not None
    ]
    other = [
        c
        for c in mcs
        if isinstance(c, dict)
        and c not in weight_conds
        and c not in money_conds
    ]

    parts: list[str] = []
    w_seg = _format_weight_segment(weight_conds)
    if w_seg:
        parts.append(w_seg)
    elif weight_conds:
        parts.extend(
            s
            for c in weight_conds
            if (s := _format_condition(c))
        )
    m_seg = _format_money_segment(money_conds)
    if m_seg:
        parts.append(m_seg)
    elif money_conds:
        parts.extend(
            s
            for c in money_conds
            if (s := _format_condition(c))
        )
    for c in other:
        s = _format_condition(c)
        if s:
            parts.append(s)
    if not parts:
        return "Tier conditions"
    return " · ".join(parts)


def _price_pair(method: Json.Object, factor: Decimal) -> tuple[str, str] | None:
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
        return (
            Currency.format_amount(amt, cur),
            Currency.format_amount(new_amt, cur),
        )
    if typename == "DeliveryParticipant":
        ff = rp.get("fixedFee")
        if not isinstance(ff, dict):
            return None
        amt = ff.get("amount")
        cur = ff.get("currencyCode")
        if not isinstance(amt, str) or not isinstance(cur, str):
            return None
        new_amt = _scale_money(amt, factor)
        return (
            Currency.format_amount(amt, cur),
            Currency.format_amount(new_amt, cur),
        )
    return None


def _price_pair_offset(
    method: Json.Object,
    delta: Decimal,
) -> tuple[str, str] | None:
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
        new_amt = _offset_money(amt, delta)
        return (
            Currency.format_amount(amt, cur),
            Currency.format_amount(new_amt, cur),
        )
    if typename == "DeliveryParticipant":
        ff = rp.get("fixedFee")
        if not isinstance(ff, dict):
            return None
        amt = ff.get("amount")
        cur = ff.get("currencyCode")
        if not isinstance(amt, str) or not isinstance(cur, str):
            return None
        new_amt = _offset_money(amt, delta)
        return (
            Currency.format_amount(amt, cur),
            Currency.format_amount(new_amt, cur),
        )
    return None


def preview_rate_changes(
    shop_domain: str,
    access_token: str,
    rate_name: str,
    percent: float,
    profile_id: str | None = None,
    zone_id: str | None = None,
    adjustment_mode: Literal["percent", "offset"] = "percent",
) -> tuple[list[Json.Object], list[str]]:
    """
    Returns (profiles, warnings) where each profile has
    id, name, zones: [{ id, name, rows: [{ id, boundary, current, new }] }].
    """
    rows, warnings = collect_methods_and_warnings(shop_domain, access_token)
    factor: Decimal | None = None
    amount_delta: Decimal | None = None
    if adjustment_mode == "percent":
        factor = Decimal(1) + Decimal(str(percent)) / Decimal(100)
    else:
        amount_delta = Decimal(str(percent))

    acc: dict[str, Json.Object] = {}

    for row in rows:
        if not _row_matches_profile_zone(row, profile_id, zone_id):
            continue
        m = row.get("method")
        if not isinstance(m, dict) or m.get("name") != rate_name:
            continue
        if adjustment_mode == "percent":
            assert factor is not None
            if _method_update_input(m, factor) is None:
                continue
            pair = _price_pair(m, factor)
        else:
            assert amount_delta is not None
            if _method_update_input_offset(m, amount_delta) is None:
                continue
            pair = _price_pair_offset(m, amount_delta)
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
        boundary = _format_boundary(m)

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

    out: list[Json.Object] = []
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
        zones_out: list[Json.Object] = []
        for zid in sorted(
            zmap.keys(),
            key=lambda z: (
                str(cast(Json.Object, cast(Json.Object, zmap)[z]).get("name", "")).lower(),
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
                cast(list[Json.Object], rows_list),
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
        out.append(
            {
                "id": pid,
                "name": pname,
                "zones": zones_out,
            }
        )

    return out, warnings


def adjust_rates_by_name_percent(
    shop_domain: str,
    access_token: str,
    rate_name: str,
    percent: float,
    profile_id: str | None = None,
    zone_id: str | None = None,
    adjustment_mode: Literal["percent", "offset"] = "percent",
) -> tuple[int, list[str], list[str]]:
    """
    Returns (updated_method_count, warnings, user_error_messages).
    """
    rows, warnings = collect_methods_and_warnings(shop_domain, access_token)
    factor: Decimal | None = None
    amount_delta: Decimal | None = None
    if adjustment_mode == "percent":
        factor = Decimal(1) + Decimal(str(percent)) / Decimal(100)
    else:
        amount_delta = Decimal(str(percent))

    by_profile: dict[str, dict[str, dict[str, list[Json.Object]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )

    updated = 0
    for row in rows:
        if not _row_matches_profile_zone(row, profile_id, zone_id):
            continue
        m = row.get("method")
        if not isinstance(m, dict):
            continue
        if m.get("name") != rate_name:
            continue
        if adjustment_mode == "percent":
            assert factor is not None
            inp = _method_update_input(m, factor)
        else:
            assert amount_delta is not None
            inp = _method_update_input_offset(m, amount_delta)
        if inp is None:
            warnings.append(
                f"Skipped a rate named {rate_name!r} (unsupported rate type or missing price)."
            )
            continue
        pid = row.get("profileId")
        lg = row.get("locationGroupId")
        zid = row.get("zoneId")
        if not isinstance(pid, str) or not isinstance(lg, str) or not isinstance(zid, str):
            continue
        by_profile[pid][lg][zid].append(inp)
        updated += 1

    if updated == 0:
        return 0, warnings, ["No matching adjustable rates found for that name."]

    mut = FileLoader.load("delivery_profile_update.gql")
    user_msgs: list[str] = []

    for profile_id, by_lg in by_profile.items():
        for lg_id, by_zone in by_lg.items():
            for zone_batch in _zone_method_update_batches(
                by_zone, _MAX_DELIVERY_METHOD_UPDATES_PER_MUTATION
            ):
                gql = GraphQL.send(
                    shop_domain,
                    access_token,
                    mut,
                    cast(
                        Json.Object,
                        {
                            "id": profile_id,
                            "profile": {
                                "locationGroupsToUpdate": [
                                    {
                                        "id": lg_id,
                                        "zonesToUpdate": cast(list[Json.Value], zone_batch),
                                    }
                                ]
                            },
                        },
                    ),
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
                        if not isinstance(ue, dict):
                            continue
                        msg = ue.get("message")
                        if isinstance(msg, str):
                            user_msgs.append(msg)

    return updated, warnings, user_msgs
