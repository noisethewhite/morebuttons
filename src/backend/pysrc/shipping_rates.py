from __future__ import annotations

import io
import csv
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from .catalog_cache import get_shipping_catalog, invalidate_shipping_catalog
from .fileloader import FileLoader
from .graphql import GraphQL
from .graphqldc.shipping import (
    CatalogRow,
    CatalogRowList,
    DeliveryCountry,
    DeliveryParticipant,
    DeliveryProfileInput,
    DeliveryProfileLocationGroupInput,
    DeliveryProfileQueryData,
    DeliveryProfilesQueryData,
    DeliveryProfileUpdateData,
    DeliveryProfileUpdateVariables,
    DeliveryRateDefinition,
    MethodDefinition,
    MethodDefinitionInputsByProfile,
    PreviewProfileBlock,
    PreviewRateRow,
    PreviewZoneBlock
)
from .symbols import Currency


# Cap methodDefinitionsToUpdate per deliveryProfileUpdate mutation (total across zones in
# that mutation). Avoids oversized payloads, timeouts, and Shopify input limits.
_MUTATION_CAP = 25


def collect_methods_and_warnings(
    shop_domain: str,
    access_token: str,
) -> tuple[CatalogRowList, list[str]]:
    warnings: list[str] = []
    rows: CatalogRowList = CatalogRowList()

    q_profiles = FileLoader.load("delivery_profiles_page.gql")
    q_zones = FileLoader.load("delivery_profile_group_zones.gql")

    after_profiles: str | None = None
    while True:
        parsed = GraphQL.send(
            shop_domain,
            access_token,
            q_profiles,
            {"first": 50, "after": after_profiles},
            expected_type=DeliveryProfilesQueryData,
        )
        if parsed is None:
            warnings.append(
                "Unexpected response shape from deliveryProfiles" + \
                " query (internal validation failed)."
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

        nxt = conn.pageInfo.next_page_cursor()
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
    rows: CatalogRowList,
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
            expected_type=DeliveryProfileQueryData,
        )
        if parsed is None:
            warnings.append(
                "Unexpected response shape from deliveryProfile query" + \
                "(internal validation failed)."
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
                    f"More than 250 method definitions in a zone; " + \
                    "only the first page was loaded (zone {zid})."
                )
            for medge in md.edges:
                mnode = medge.node
                rows.append(
                    CatalogRow(
                        profileId=profile_id,
                        profileName=profile_name,
                        locationGroupId=location_group_id,
                        zoneId=zid,
                        zoneName=zname,
                        method=mnode,
                        zoneCountries=zone.countries,
                    )
                )

        nxt = zconn.pageInfo.next_page_cursor()
        if nxt is None:
            break
        after_zones = nxt

@dataclass
class _PreviewZoneAccum:
    name: str
    rows: list[PreviewRateRow] = field(default_factory=list)


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
) -> tuple[list[PreviewProfileBlock], list[str]]:
    """
    Returns (profiles, warnings) where each profile has
    id, name, zones: [{ id, name, rows: [{ id, boundary, current, new }] }].

    Uses the in-memory shipping catalog loaded by the catalog job (no extra
    GraphQL). ``access_token`` is unused but kept for API compatibility.
    """
    cached = get_shipping_catalog(shop_domain)
    if cached is None:
        raise RuntimeError(
            "Shipping catalog is not loaded yet. Wait for the loading progress to finish."
        )
    rows, warnings = cached
    return preview_rate_changes_from_rows(
        rows,
        warnings,
        rate_name,
        percent,
        profile_id,
        zone_id,
        adjustment_mode,
    )


def preview_rate_changes_from_rows(
    rows: CatalogRowList,
    warnings: list[str],
    rate_name: str,
    percent: float,
    profile_id: str | None = None,
    zone_id: str | None = None,
    adjustment_mode: Literal["percent", "offset"] = "percent",
) -> tuple[list[PreviewProfileBlock], list[str]]:
    """
    Pure CPU preview from an already-fetched :class:`CatalogRowList`.
    """
    factor: Decimal | None = None
    amount_delta: Decimal | None = None
    if adjustment_mode == "percent":
        factor = Decimal(1) + Decimal(str(percent)) / Decimal(100)
    else:
        amount_delta = Decimal(str(percent))

    acc: dict[str, _PreviewProfileAccum] = {}
    w = list(warnings)

    for row in rows:
        if not row.matches_profile_zone(profile_id, zone_id):
            continue
        m = row.method
        if m.name != rate_name:
            continue
        if adjustment_mode == "percent":
            assert factor is not None
            if m.update_input_percent(factor) is None:
                continue
            pair = m.price_pair_percent(factor)
        else:
            assert amount_delta is not None
            if m.update_input_offset(amount_delta) is None:
                continue
            pair = m.price_pair_offset(amount_delta)
        if pair is None:
            continue
        cur_s, new_s = pair
        pid = row.profileId
        zid = row.zoneId
        pname = row.profileName
        zname = row.zoneName
        mid = m.id
        boundary = m.format_boundary()

        if pid not in acc:
            acc[pid] = _PreviewProfileAccum(name=pname, zones={})
        prof = acc[pid]
        if zid not in prof.zones:
            prof.zones[zid] = _PreviewZoneAccum(name=zname)
        prof.zones[zid].rows.append(
            PreviewRateRow(
                id=mid,
                boundary=boundary,
                current=cur_s,
                new=new_s,
            )
        )

    out: list[PreviewProfileBlock] = []
    for pid in sorted(acc.keys(), key=lambda i: (acc[i].name.lower(), i)):
        pa = acc[pid]
        zones_out: list[PreviewZoneBlock] = []
        for zid in sorted(pa.zones.keys(), key=lambda z: (pa.zones[z].name.lower(), z)):
            zb = pa.zones[zid]
            rows_sorted = sorted(
                zb.rows,
                key=lambda r: (r.boundary, r.id),
            )
            zones_out.append(
                PreviewZoneBlock(id=zid, name=zb.name, rows=rows_sorted)
            )
        out.append(
            PreviewProfileBlock(id=pid, name=pa.name, zones=zones_out)
        )

    return out, w


def adjust_rates_by_name_percent(
    shop_domain: str,
    access_token: str,
    rate_name: str,
    percent: float,
    profile_id: str | None = None,
    zone_id: str | None = None,
    adjustment_mode: Literal["percent", "offset"] = "percent"
) -> tuple[int, list[str], list[str]]:
    """
    Returns (updated_method_count, warnings, user_error_messages).
    Uses cached catalog rows from the shipping load job.
    """
    cached = get_shipping_catalog(shop_domain)
    if cached is None:
        raise RuntimeError(
            "Shipping catalog is not loaded. Reload shipping data before applying changes."
        )
    rows, warnings = cached
    by_profile = MethodDefinitionInputsByProfile()
    updated, warnings = by_profile.update_by_name_percent(
        rows, warnings, rate_name, percent, profile_id, zone_id, adjustment_mode
    )

    mut = FileLoader.load("delivery_profile_update.gql")
    user_msgs: list[str] = []

    for profile_id_loop, by_lg in by_profile.items():
        for lg_id, by_zone in by_lg.items():
            for zone_batch in by_zone.update_batches(_MUTATION_CAP):
                parsed, soft_errs = GraphQL.send(
                    shop_domain,
                    access_token,
                    query=mut,
                    variables=DeliveryProfileUpdateVariables(
                        id=profile_id_loop,
                        profile=DeliveryProfileInput(
                            locationGroupsToUpdate=[
                                DeliveryProfileLocationGroupInput(
                                    id=lg_id,
                                    zonesToUpdate=zone_batch,
                                )
                            ]
                        ),
                    ).to_json(),
                    expected_type=DeliveryProfileUpdateData,
                    raise_on_graphql_error=False,
                )
                user_msgs.extend(soft_errs)
                if parsed is None:
                    if not soft_errs:
                        user_msgs.append(
                            "Unexpected response shape from " + \
                            "deliveryProfileUpdate (internal validation failed)."
                        )
                    continue
                dpu = parsed.deliveryProfileUpdate
                if dpu is None:
                    continue
                for ue in dpu.userErrors:
                    msg = ue.message
                    if isinstance(msg, str):
                        user_msgs.append(msg)

    invalidate_shipping_catalog(shop_domain)
    return updated, warnings, user_msgs


_INF = float("inf")
_LOW_OPS = frozenset({"GREATER_THAN_OR_EQUAL_TO", "GREATER_THAN"})
_HIGH_OPS = frozenset({"LESS_THAN_OR_EQUAL_TO", "LESS_THAN"})
_KG_FACTORS: dict[str, float] = {
    "GRAMS": 1 / 1000,
    "G": 1 / 1000,
    "POUNDS": 0.453592,
    "LB": 0.453592,
    "LBS": 0.453592,
    "OUNCES": 0.0283495,
    "OZ": 0.0283495,
}


def _to_kg(value: float, unit: str) -> float:
    return value * _KG_FACTORS.get(unit.upper(), 1.0)


def _fmt_kg(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    s = f"{v:.3f}".rstrip("0")
    return s.rstrip(".")


def _extract_weight_interval(method: MethodDefinition) -> tuple[float, float]:
    lower = 0.0
    upper = _INF
    for cond in (method.methodConditions or []):
        t = cond.parse_weight_triple()
        if not t:
            continue
        op, val, unit = t
        val_kg = _to_kg(val, unit)
        if op in _LOW_OPS:
            lower = max(lower, val_kg)
        elif op in _HIGH_OPS:
            upper = min(upper, val_kg)
    return lower, upper


def _rate_price_str(rp: object) -> str:
    if isinstance(rp, DeliveryRateDefinition):
        return Currency.format_amount(rp.price.amount, rp.price.currencyCode)
    if isinstance(rp, DeliveryParticipant):
        return "Carrier calculated"
    return ""


def _build_segments(
    lower_values: set[float],
    max_finite_upper: float | None,
    has_open_upper: bool,
) -> list[tuple[float, float]]:
    split_pts = sorted(lower_values)
    if not has_open_upper and max_finite_upper is not None:
        if max_finite_upper not in lower_values:
            split_pts.append(max_finite_upper)
            split_pts.sort()
    segments: list[tuple[float, float]] = [
        (split_pts[i], split_pts[i + 1]) for i in range(len(split_pts) - 1)
    ]
    if has_open_upper and split_pts:
        segments.append((split_pts[-1], _INF))
    if not segments and split_pts:
        segments = [(split_pts[0], _INF)]
    return segments


def _fmt_upper(seg_hi: float, lower_values: set[float]) -> str:
    if seg_hi == _INF:
        return ""
    if seg_hi in lower_values:
        return _fmt_kg(round(seg_hi - 0.001, 3))
    return _fmt_kg(seg_hi)


def _find_price(col_data: dict[str, list[tuple[float, float, str]]], col: str, seg_lo: float) -> str:
    for m_lo, m_hi, m_price in col_data.get(col, []):
        if m_lo <= seg_lo <= m_hi:
            return m_price
    return ""


def _col_sort_key(col: str) -> str:
    return "~" if col == "ROW" else col


def _write_csv(
    col_data: dict[str, list[tuple[float, float, str]]],
    lower_values: set[float],
    max_finite_upper: float | None,
    has_open_upper: bool,
) -> str:
    segments = _build_segments(lower_values, max_finite_upper, has_open_upper)
    cols = sorted(col_data.keys(), key=_col_sort_key)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Weight from (kg)", "Weight to (kg)", *cols])
    for lo, hi in segments:
        writer.writerow([
            _fmt_kg(lo),
            _fmt_upper(hi, lower_values),
            *(_find_price(col_data, c, lo) for c in cols),
        ])
    return buf.getvalue()


def _iter_country_cols(
    countries: list[DeliveryCountry],
    fallback: str,
    province_level: bool,
) -> list[str]:
    """
    Return the column key(s) that represent the given country list.

    Country-level view: one column per country code (e.g. "DE").
    Province-level view: one column per province for province-restricted countries
    (e.g. "US-CA"), but whole-country entries keep a single country-code column.
    """
    if not countries:
        return [fallback]
    cols: list[str] = []
    for country in countries:
        if country.code.restOfWorld:
            cols.append("ROW")
            continue
        cc = country.code.countryCode or fallback
        provs = country.provinces or []
        if province_level and provs:
            for prov in provs:
                cols.append(f"{cc}-{prov.code}")
        else:
            cols.append(cc)
    return cols


def _build_col_data(
    filtered: list[CatalogRow],
    province_level: bool,
) -> tuple[dict[str, list[tuple[float, float, str]]], set[float], float | None, bool]:
    col_data: dict[str, list[tuple[float, float, str]]] = {}
    lower_values: set[float] = set()
    max_finite_upper: float | None = None
    has_open_upper = False

    for row in filtered:
        lower, upper = _extract_weight_interval(row.method)
        lower_values.add(lower)
        if upper == _INF:
            has_open_upper = True
        else:
            max_finite_upper = upper if max_finite_upper is None else max(max_finite_upper, upper)

        price = _rate_price_str(row.method.rateProvider)
        cols = _iter_country_cols(row.zoneCountries or [], row.zoneName, province_level)
        for col in cols:
            col_data.setdefault(col, []).append((lower, upper, price))

    return col_data, lower_values, max_finite_upper, has_open_upper


def build_rates_csv(
    rows: CatalogRowList,
    rate_name: str,
    profile_id: str | None,
) -> str:
    """
    Country-level CSV: one column per 2-letter country code (or ROW).
    Province-restricted countries still get a single country-code column.
    Falls back to zone name if the catalog was loaded without country data.
    """
    filtered = [
        r for r in rows
        if r.method.name == rate_name and r.matches_profile_zone(profile_id, None)
    ]
    if not filtered:
        return ""
    col_data, lower_values, max_finite_upper, has_open_upper = _build_col_data(
        filtered, province_level=False
    )
    return _write_csv(col_data, lower_values, max_finite_upper, has_open_upper)


def build_rates_province_csv(
    rows: CatalogRowList,
    rate_name: str,
    profile_id: str | None,
) -> str:
    """
    Province-level CSV: only countries that have province restrictions AND where
    at least two provinces have different rates for at least one weight segment.
    Each qualifying country is expanded to CC-PP columns (e.g. US-CA, US-TX).
    Returns an empty string when no such countries exist.
    """
    filtered = [
        r for r in rows
        if r.method.name == rate_name and r.matches_profile_zone(profile_id, None)
    ]
    if not filtered:
        return ""

    # Countries that appear with province restrictions in any row.
    province_ccs: set[str] = set()
    for row in filtered:
        for ctry in (row.zoneCountries or []):
            if not ctry.code.restOfWorld and ctry.provinces:
                cc = ctry.code.countryCode
                if cc:
                    province_ccs.add(cc)

    if not province_ccs:
        return ""

    # Build col_data (CC-PP columns) and weight boundaries from all filtered rows.
    # Weight boundaries include the whole selection so segments align with the
    # country CSV.
    col_data: dict[str, list[tuple[float, float, str]]] = {}
    lower_values: set[float] = set()
    max_finite_upper: float | None = None
    has_open_upper = False

    for row in filtered:
        lower, upper = _extract_weight_interval(row.method)
        lower_values.add(lower)
        if upper == _INF:
            has_open_upper = True
        else:
            max_finite_upper = (
                upper if max_finite_upper is None else max(max_finite_upper, upper)
            )
        price = _rate_price_str(row.method.rateProvider)

        for ctry in (row.zoneCountries or []):
            if ctry.code.restOfWorld:
                continue
            cc = ctry.code.countryCode or ""
            if cc not in province_ccs:
                continue
            for prov in (ctry.provinces or []):
                col_data.setdefault(f"{cc}-{prov.code}", []).append(
                    (lower, upper, price)
                )

    if not col_data:
        return ""

    segments = _build_segments(lower_values, max_finite_upper, has_open_upper)

    # Group province columns by parent country code.
    cc_to_cols: dict[str, list[str]] = {}
    for col in col_data:
        cc = col.split("-", 1)[0]
        cc_to_cols.setdefault(cc, []).append(col)

    # Keep only countries where provinces actually have different prices.
    keep: set[str] = set()
    for cc, p_cols in cc_to_cols.items():
        if len(p_cols) == 1:
            # Single province can't be compared — include it as-is.
            keep.update(p_cols)
            continue
        for lo, _ in segments:
            prices = {_find_price(col_data, p, lo) for p in p_cols}
            if len(prices) > 1:
                keep.update(p_cols)
                break

    if not keep:
        return ""

    final_data = {col: col_data[col] for col in col_data if col in keep}
    return _write_csv(final_data, lower_values, max_finite_upper, has_open_upper)
