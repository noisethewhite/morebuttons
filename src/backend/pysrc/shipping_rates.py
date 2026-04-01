from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from .fileloader import FileLoader
from .graphql import GraphQL
from .graphqldc.shipping import (
    CatalogRow,
    CatalogRowList,
    DeliveryProfileInputDC,
    DeliveryProfileLocationGroupInputDC,
    DeliveryProfileQueryDataDC,
    DeliveryProfilesQueryDataDC,
    DeliveryProfileUpdateDataDC,
    DeliveryProfileUpdateVariablesDC,
    MethodDefinitionUpdateInputsByProfile,
    PreviewProfileBlockDC,
    PreviewRateRowDC,
    PreviewZoneBlockDC
)


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
            expected_type=DeliveryProfilesQueryDataDC,
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
            expected_type=DeliveryProfileQueryDataDC,
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
                    )
                )

        nxt = GraphQL.next_page_cursor(zconn.pageInfo)
        if nxt is None:
            break
        after_zones = nxt

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

    by_profile= MethodDefinitionUpdateInputsByProfile()

    updated = 0
    for row in rows:
        if not row.matches_profile_zone(profile_id, zone_id):
            continue
        m = row.method
        if m.name != rate_name:
            continue
        if adjustment_mode == "percent":
            assert factor is not None
            inp = m.update_input_percent(factor)
        else:
            assert amount_delta is not None
            inp = m.update_input_offset(amount_delta)
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
            for zone_batch in by_zone.update_batches(_MUTATION_CAP):
                parsed, soft_errs = GraphQL.send(
                    shop_domain,
                    access_token,
                    query=mut,
                    variables=DeliveryProfileUpdateVariablesDC(
                        id=profile_id_loop,
                        profile=DeliveryProfileInputDC(
                            locationGroupsToUpdate=[
                                DeliveryProfileLocationGroupInputDC(
                                    id=lg_id,
                                    zonesToUpdate=zone_batch,
                                )
                            ]
                        ),
                    ).to_json(),
                    expected_type=DeliveryProfileUpdateDataDC,
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

    return updated, warnings, user_msgs
