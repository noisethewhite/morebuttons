from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, cast

from pydantic import TypeAdapter

from .fileloader import FileLoader
from .graphql import GraphQL
from .graphqldc.shipping import (
    CatalogRowDC,
    DeliveryParticipantInputDC,
    DeliveryProfileInputDC,
    DeliveryProfileLocationGroupInputDC,
    DeliveryProfileQueryDataDC,
    DeliveryProfilesQueryDataDC,
    DeliveryProfileUpdateDataDC,
    DeliveryProfileUpdateVariablesDC,
    DeliveryRateDefinitionDC,
    DeliveryRateDefinitionInputDC,
    MethodConditionDC,
    MethodDefinitionNodeDC,
    MethodDefinitionUpdateInputDC,
    MoneyInputDC,
    MoneyV2CriteriaDC,
    PreviewProfileBlockDC,
    PreviewRateRowDC,
    PreviewZoneBlockDC,
    WeightCriteriaDC,
    ZoneUpdateInputDC,
)
from .symbols import Currency, ComparisonSymbol
from .web_types import Json
from .utils import Utils


# Cap methodDefinitionsToUpdate per deliveryProfileUpdate mutation (total across zones in
# that mutation). Avoids oversized payloads, timeouts, and Shopify input limits.
_MAX_DELIVERY_METHOD_UPDATES_PER_MUTATION = 25


def _delivery_profile_update_variables_to_json(
    v: DeliveryProfileUpdateVariablesDC,
) -> Json.Object:
    return cast(
        Json.Object,
        TypeAdapter(DeliveryProfileUpdateVariablesDC).dump_python(
            v, exclude_none=True, mode="json"
        ),
    )


def _scale_money(amount: str, factor: Decimal) -> str:
    d = Decimal(amount)
    return str((d * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _offset_money(amount: str, delta: Decimal) -> str:
    d = Decimal(amount) + delta
    if d < 0:
        d = Decimal(0)
    return str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _method_update_input(
    method: MethodDefinitionNodeDC,
    factor: Decimal,
) -> MethodDefinitionUpdateInputDC | None:
    rp = method.rateProvider
    if rp is None:
        return None
    if isinstance(rp, DeliveryRateDefinitionDC):
        amt = rp.price.amount
        cur = rp.price.currencyCode
        return MethodDefinitionUpdateInputDC(
            id=method.id,
            rateDefinition=DeliveryRateDefinitionInputDC(
                id=rp.id,
                price=MoneyInputDC(
                    amount=_scale_money(amt, factor),
                    currencyCode=cur,
                ),
            ),
        )
    ff = rp.fixedFee
    if ff is None:
        return None
    amt = ff.amount
    cur = ff.currencyCode
    return MethodDefinitionUpdateInputDC(
        id=method.id,
        participant=DeliveryParticipantInputDC(
            id=rp.id,
            fixedFee=MoneyInputDC(
                amount=_scale_money(amt, factor),
                currencyCode=cur,
            ),
        ),
    )


def _method_update_input_offset(
    method: MethodDefinitionNodeDC,
    delta: Decimal,
) -> MethodDefinitionUpdateInputDC | None:
    rp = method.rateProvider
    if rp is None:
        return None
    if isinstance(rp, DeliveryRateDefinitionDC):
        amt = rp.price.amount
        cur = rp.price.currencyCode
        new_amt = _offset_money(amt, delta)
        return MethodDefinitionUpdateInputDC(
            id=method.id,
            rateDefinition=DeliveryRateDefinitionInputDC(
                id=rp.id,
                price=MoneyInputDC(amount=new_amt, currencyCode=cur),
            ),
        )
    ff = rp.fixedFee
    if ff is None:
        return None
    amt = ff.amount
    cur = ff.currencyCode
    new_amt = _offset_money(amt, delta)
    return MethodDefinitionUpdateInputDC(
        id=method.id,
        participant=DeliveryParticipantInputDC(
            id=rp.id,
            fixedFee=MoneyInputDC(amount=new_amt, currencyCode=cur),
        ),
    )


def _zone_method_update_batches(
    by_zone: dict[str, list[MethodDefinitionUpdateInputDC]],
    max_method_updates_per_mutation: int,
) -> list[list[ZoneUpdateInputDC]]:
    """
    Split zone → method update inputs into several GraphQL mutations.

    Each zone's list is split into slices of at most ``max_method_updates_per_mutation``,
    then slices are packed into batches so each batch has at most that many updates total
    (multiple zones may share one mutation when they fit).
    """
    pieces: list[tuple[str, list[MethodDefinitionUpdateInputDC]]] = []
    for zone_id, methods in by_zone.items():
        for chunk in Utils.chunks(methods, max_method_updates_per_mutation):
            pieces.append((zone_id, chunk))
    batches: list[list[ZoneUpdateInputDC]] = []
    cur: list[ZoneUpdateInputDC] = []
    cur_total = 0
    for zid, mets in pieces:
        n = len(mets)
        if cur_total + n > max_method_updates_per_mutation and cur:
            batches.append(cur)
            cur = []
            cur_total = 0
        cur.append(
            ZoneUpdateInputDC(id=zid, methodDefinitionsToUpdate=mets)
        )
        cur_total += n
    if cur:
        batches.append(cur)
    return batches


def collect_methods_and_warnings(
    shop_domain: str,
    access_token: str,
) -> tuple[list[CatalogRowDC], list[str]]:
    warnings: list[str] = []
    rows: list[CatalogRowDC] = []

    q_profiles = FileLoader.load("delivery_profiles_page.gql")
    q_zones = FileLoader.load("delivery_profile_group_zones.gql")

    after_profiles: str | None = None
    while True:
        parsed = GraphQL.send(
            shop_domain,
            access_token,
            q_profiles,
            {"first": 50, "after": after_profiles},
            expected_type=DeliveryProfilesQueryDataDC,
        )
        if parsed is None:
            warnings.append(
                "Unexpected response shape from deliveryProfiles query (internal validation failed)."
            )
            break
        conn = parsed.deliveryProfiles
        for edge in conn.edges:
            node_p = edge.node
            pid = node_p.id
            pname = node_p.name or ""
            plgs = node_p.profileLocationGroups or []
            for plg in plgs:
                lg_id = plg.locationGroup.id
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

        nxt = GraphQL.next_page_cursor(conn.pageInfo)
        if nxt is None:
            break
        after_profiles = nxt

    return rows, warnings


def _append_zone_methods(
    shop_domain: str,
    access_token: str,
    q_zones: str,
    profile_id: str,
    profile_name: str,
    location_group_id: str,
    rows: list[CatalogRowDC],
    warnings: list[str],
) -> None:
    after_zones: str | None = None
    while True:
        parsed = GraphQL.send(
            shop_domain,
            access_token,
            q_zones,
            {
                "profileId": profile_id,
                "locationGroupId": location_group_id,
                "zonesFirst": 50,
                "zonesAfter": after_zones,
            },
            expected_type=DeliveryProfileQueryDataDC,
        )
        if parsed is None:
            warnings.append(
                "Unexpected response shape from deliveryProfile query (internal validation failed)."
            )
            break
        dp = parsed.deliveryProfile
        if not dp or not dp.profileLocationGroups:
            break
        plg0 = dp.profileLocationGroups[0]
        zconn = plg0.locationGroupZones
        for zedge in zconn.edges:
            zn = zedge.node
            zone = zn.zone
            zid = zone.id
            zname = zone.name or ""
            md = zn.methodDefinitions
            if md.pageInfo.hasNextPage is True:
                warnings.append(
                    f"More than 250 method definitions in a zone; only the first page was loaded (zone {zid})."
                )
            for medge in md.edges:
                mnode = medge.node
                rows.append(
                    CatalogRowDC(
                        profileId=profile_id,
                        profileName=profile_name,
                        locationGroupId=location_group_id,
                        zoneId=zid,
                        zoneName=zname,
                        method=mnode,
                    )
                )

        nxt = GraphQL.next_page_cursor(zconn.pageInfo)
        if nxt is None:
            break
        after_zones = nxt


def unique_rate_names(rows: list[CatalogRowDC]) -> list[str]:
    names: set[str] = set()
    for row in rows:
        n = row.method.name
        if n:
            names.add(n)
    return sorted(names)


def build_delivery_profile_filters(
    rows: list[CatalogRowDC],
) -> tuple[list[Json.Object], Json.Object]:
    """Unique delivery profiles and zones per profile (for filter dropdowns)."""
    profiles_map: dict[str, str] = {}
    zones_by_profile: dict[str, dict[str, str]] = defaultdict(dict)
    for row in rows:
        profiles_map[row.profileId] = row.profileName
        zones_by_profile[row.profileId][row.zoneId] = row.zoneName
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
    row: CatalogRowDC,
    profile_id: str | None,
    zone_id: str | None,
) -> bool:
    if profile_id is not None and row.profileId != profile_id:
        return False
    if zone_id is not None and row.zoneId != zone_id:
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


def _parse_weight_triple(
    cond: MethodConditionDC,
) -> tuple[str, float, str] | None:
    crit = cond.conditionCriteria
    if not isinstance(crit, WeightCriteriaDC):
        return None
    op = cond.operator
    if not isinstance(op, str):
        return None
    vdisp = Utils.to_float(crit.value)
    if vdisp is None:
        return None
    return (op, vdisp, crit.unit)


def _parse_money_triple(
    cond: MethodConditionDC,
) -> tuple[str, str, str] | None:
    crit = cond.conditionCriteria
    if not isinstance(crit, MoneyV2CriteriaDC):
        return None
    op = cond.operator
    if not isinstance(op, str):
        return None
    return (op, str(crit.amount), crit.currencyCode.upper())


def _format_weight_segment(conds: list[MethodConditionDC]) -> str | None:
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


def _format_money_segment(conds: list[MethodConditionDC]) -> str | None:
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


def _format_condition(cond: MethodConditionDC) -> str | None:
    op = cond.operator
    crit = cond.conditionCriteria
    if not isinstance(op, str) or crit is None:
        return None
    sym = ComparisonSymbol.get(op)
    if isinstance(crit, WeightCriteriaDC):
        vdisp = Utils.to_float(crit.value)
        if vdisp is None:
            return None
        ul = _weight_unit_label(crit.unit)
        return f"Weight: {sym} {_fmt_weight_num(vdisp)} {ul}"
    disp = Currency.format_amount(str(crit.amount), crit.currencyCode)
    return f"Order total: {sym} {disp}"


def _format_boundary(method: MethodDefinitionNodeDC) -> str:
    mcs = method.methodConditions
    if not mcs or len(mcs) == 0:
        return "No tier limits"
    weight_conds = [c for c in mcs if _parse_weight_triple(c) is not None]
    money_conds = [c for c in mcs if _parse_money_triple(c) is not None]
    other = [
        c
        for c in mcs
        if c not in weight_conds
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


def _price_pair(
    method: MethodDefinitionNodeDC, factor: Decimal
) -> tuple[str, str] | None:
    rp = method.rateProvider
    if rp is None:
        return None
    if isinstance(rp, DeliveryRateDefinitionDC):
        amt = rp.price.amount
        cur = rp.price.currencyCode
        new_amt = _scale_money(amt, factor)
        return (
            Currency.format_amount(amt, cur),
            Currency.format_amount(new_amt, cur),
        )
    ff = rp.fixedFee
    if ff is None:
        return None
    amt = ff.amount
    cur = ff.currencyCode
    new_amt = _scale_money(amt, factor)
    return (
        Currency.format_amount(amt, cur),
        Currency.format_amount(new_amt, cur),
    )


def _price_pair_offset(
    method: MethodDefinitionNodeDC,
    delta: Decimal,
) -> tuple[str, str] | None:
    rp = method.rateProvider
    if rp is None:
        return None
    if isinstance(rp, DeliveryRateDefinitionDC):
        amt = rp.price.amount
        cur = rp.price.currencyCode
        new_amt = _offset_money(amt, delta)
        return (
            Currency.format_amount(amt, cur),
            Currency.format_amount(new_amt, cur),
        )
    ff = rp.fixedFee
    if ff is None:
        return None
    amt = ff.amount
    cur = ff.currencyCode
    new_amt = _offset_money(amt, delta)
    return (
        Currency.format_amount(amt, cur),
        Currency.format_amount(new_amt, cur),
    )


@dataclass
class _PreviewZoneAccum:
    name: str
    rows: list[PreviewRateRowDC] = field(default_factory=list)


@dataclass
class _PreviewProfileAccum:
    name: str
    zones: dict[str, _PreviewZoneAccum] = field(default_factory=dict)


def preview_rate_changes(
    shop_domain: str,
    access_token: str,
    rate_name: str,
    percent: float,
    profile_id: str | None = None,
    zone_id: str | None = None,
    adjustment_mode: Literal["percent", "offset"] = "percent",
) -> tuple[list[PreviewProfileBlockDC], list[str]]:
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

    acc: dict[str, _PreviewProfileAccum] = {}

    for row in rows:
        if not _row_matches_profile_zone(row, profile_id, zone_id):
            continue
        m = row.method
        if m.name != rate_name:
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
        pid = row.profileId
        zid = row.zoneId
        pname = row.profileName
        zname = row.zoneName
        mid = m.id
        boundary = _format_boundary(m)

        if pid not in acc:
            acc[pid] = _PreviewProfileAccum(name=pname, zones={})
        prof = acc[pid]
        if zid not in prof.zones:
            prof.zones[zid] = _PreviewZoneAccum(name=zname)
        prof.zones[zid].rows.append(
            PreviewRateRowDC(
                id=mid,
                boundary=boundary,
                current=cur_s,
                new=new_s,
            )
        )

    out: list[PreviewProfileBlockDC] = []
    for pid in sorted(acc.keys(), key=lambda i: (acc[i].name.lower(), i)):
        pa = acc[pid]
        zones_out: list[PreviewZoneBlockDC] = []
        for zid in sorted(pa.zones.keys(), key=lambda z: (pa.zones[z].name.lower(), z)):
            zb = pa.zones[zid]
            rows_sorted = sorted(
                zb.rows,
                key=lambda r: (r.boundary, r.id),
            )
            zones_out.append(
                PreviewZoneBlockDC(id=zid, name=zb.name, rows=rows_sorted)
            )
        out.append(
            PreviewProfileBlockDC(id=pid, name=pa.name, zones=zones_out)
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

    by_profile: dict[str, dict[str, dict[str, list[MethodDefinitionUpdateInputDC]]]] = (
        defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    )

    updated = 0
    for row in rows:
        if not _row_matches_profile_zone(row, profile_id, zone_id):
            continue
        m = row.method
        if m.name != rate_name:
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
        pid = row.profileId
        lg = row.locationGroupId
        zid = row.zoneId
        by_profile[pid][lg][zid].append(inp)
        updated += 1

    if updated == 0:
        return 0, warnings, ["No matching adjustable rates found for that name."]

    mut = FileLoader.load("delivery_profile_update.gql")
    user_msgs: list[str] = []

    for profile_id_loop, by_lg in by_profile.items():
        for lg_id, by_zone in by_lg.items():
            for zone_batch in _zone_method_update_batches(
                by_zone, _MAX_DELIVERY_METHOD_UPDATES_PER_MUTATION
            ):
                parsed, soft_errs = GraphQL.send(
                    shop_domain,
                    access_token,
                    query=mut,
                    variables=_delivery_profile_update_variables_to_json(
                        DeliveryProfileUpdateVariablesDC(
                            id=profile_id_loop,
                            profile=DeliveryProfileInputDC(
                                locationGroupsToUpdate=[
                                    DeliveryProfileLocationGroupInputDC(
                                        id=lg_id,
                                        zonesToUpdate=zone_batch,
                                    )
                                ]
                            ),
                        )
                    ),
                    expected_type=DeliveryProfileUpdateDataDC,
                    raise_on_graphql_error=False,
                )
                user_msgs.extend(soft_errs)
                if parsed is None:
                    if not soft_errs:
                        user_msgs.append(
                            "Unexpected response shape from deliveryProfileUpdate (internal validation failed)."
                        )
                    continue
                dpu = parsed.deliveryProfileUpdate
                if dpu is None:
                    continue
                for ue in dpu.userErrors:
                    msg = ue.message
                    if isinstance(msg, str):
                        user_msgs.append(msg)

    return updated, warnings, user_msgs
