from __future__ import annotations
from collections import defaultdict
from typing import Literal, cast

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass
from decimal import Decimal

from backend.pysrc.web_types import Json
from .common import Connection, Jsonable
from ..utils import Utils
from ..symbols import ComparisonSymbol, Currency


_CONFIG = ConfigDict(extra="ignore")


# --- delivery_profiles_page.gql ---


@dataclass(config=_CONFIG)
class DeliveryLocationGroup:
    id: str


@dataclass(config=_CONFIG)
class DeliveryProfileLocationGroup:
    locationGroup: DeliveryLocationGroup


@dataclass(config=_CONFIG)
class DeliveryProfile:
    id: str
    name: str | None = None
    profileLocationGroups: list[DeliveryProfileLocationGroup] | None = None


@dataclass(config=_CONFIG)
class DeliveryProfilesQueryDataDC:
    deliveryProfiles: Connection[DeliveryProfile]


# --- delivery_profile_group_zones.gql (method node + mutation payload) ---


@dataclass(config=_CONFIG)
class MoneyAmountDC:
    amount: str
    currencyCode: str


@dataclass(config=_CONFIG)
class DeliveryRateDefinitionDC:
    # JSON key is ``__typename``; avoid leading ``__`` (dataclass name-mangling).
    # Required fields before ``Field`` so stdlib dataclass ordering rules are satisfied.
    id: str
    price: MoneyAmountDC


@dataclass(config=_CONFIG)
class DeliveryParticipantDC:
    id: str
    fixedFee: MoneyAmountDC | None = None
    percentageOfRateFee: str | float | None = None


@dataclass(config=_CONFIG)
class WeightCriteriaDC:
    unit: str
    value: str | float | int | None = None


@dataclass(config=_CONFIG)
class MoneyV2CriteriaDC:
    amount: str
    currencyCode: str


@dataclass(config=_CONFIG)
class MethodCondition:
    field: str | None = None
    operator: str | None = None
    conditionCriteria: WeightCriteriaDC | MoneyV2CriteriaDC | None = None

    def parse_weight_triple(self) -> tuple[str, float, str] | None:
        crit = self.conditionCriteria
        if not isinstance(crit, WeightCriteriaDC):
            return None
        op = self.operator
        if not isinstance(op, str):
            return None
        vdisp = Utils.to_float(crit.value)
        if vdisp is None:
            return None
        return (op, vdisp, crit.unit)

    def parse_money_triple(self) -> tuple[str, str, str] | None:
        crit = self.conditionCriteria
        if not isinstance(crit, MoneyV2CriteriaDC):
            return None
        op = self.operator
        if not isinstance(op, str):
            return None
        return (op, str(crit.amount), crit.currencyCode.upper())

    def format_condition(self) -> str | None:
        op = self.operator
        crit = self.conditionCriteria
        if not isinstance(op, str) or crit is None:
            return None
        sym = ComparisonSymbol.get(op)
        if isinstance(crit, WeightCriteriaDC):
            vdisp = Utils.to_float(crit.value)
            if vdisp is None:
                return None
            ul = Utils.weight_unit_label(crit.unit)
            return f"Weight: {sym} {Utils.fmt_weight_num(vdisp)} {ul}"
        disp = Currency.format_amount(str(crit.amount), crit.currencyCode)
        return f"Order total: {sym} {disp}"


class MethodConditionList(list[MethodCondition]):
    def format_weight_segment(self) -> str | None:
        parsed: list[tuple[str, float, str]] = []
        for c in self:
            p = c.parse_weight_triple()
            if p:
                parsed.append(p)
        if not parsed:
            return None
        units = {u for _, _, u in parsed}
        if len(units) != 1:
            return "; ".join(
                s
                for c in self
                if (s := c.format_condition()) is not None
            ) or None
        unit = next(iter(units))
        label = Utils.weight_unit_label(unit)
        low_ops = frozenset({"GREATER_THAN_OR_EQUAL_TO", "GREATER_THAN"})
        high_ops = frozenset({"LESS_THAN_OR_EQUAL_TO", "LESS_THAN"})
        lows = [v for op, v, _ in parsed if op in low_ops]
        highs = [v for op, v, _ in parsed if op in high_ops]
        eqs = [v for op, v, _ in parsed if op == "EQUAL_TO"]

        if len(parsed) == 1:
            op, v, _u = parsed[0]
            if op in low_ops:
                return f"Weight: ≥{Utils.fmt_weight_num(v)} {label}"
            if op in high_ops:
                return f"Weight: ≤{Utils.fmt_weight_num(v)} {label}"
            if op == "EQUAL_TO":
                return f"Weight: {Utils.fmt_weight_num(v)} {label}"

        if lows and highs:
            lo = max(lows)
            hi = min(highs)
            if lo <= hi:
                return f"Weight: " + \
                f"{Utils.fmt_weight_num(lo)}–{Utils.fmt_weight_num(hi)} {label}"

        if lows and not highs:
            return f"Weight: ≥{Utils.fmt_weight_num(max(lows))} {label}"
        if highs and not lows:
            return f"Weight: ≤{Utils.fmt_weight_num(min(highs))} {label}"
        if eqs and len(eqs) == 1 and not lows and not highs:
            return f"Weight: {Utils.fmt_weight_num(eqs[0])} {label}"
        return None

    def format_money_segment(self) -> str | None:
        parsed: list[tuple[str, str, str]] = []
        for c in self:
            p = c.parse_money_triple()
            if p:
                parsed.append(p)
        if not parsed:
            return None
        currencies = {c for _, _, c in parsed}
        if len(currencies) != 1:
            return "; ".join(
                s
                for c in self
                if (s := c.format_condition()) is not None
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
                return Currency.format_range(
                    str(lo_amt), str(hi_amt), cur
                )

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


@dataclass(config=_CONFIG)
class MethodDefinition:
    id: str
    name: str | None = None
    methodConditions: list[MethodCondition] | None = None
    rateProvider: DeliveryRateDefinitionDC | DeliveryParticipantDC | None = None

    def update_input_percent(self, factor: Decimal) -> MethodDefinitionInput | None:
        rp = self.rateProvider
        if rp is None:
            return None
        if isinstance(rp, DeliveryRateDefinitionDC):
            amt = rp.price.amount
            cur = rp.price.currencyCode
            return MethodDefinitionInput(
                id=self.id,
                rateDefinition=DeliveryRateDefinitionInputDC(
                    id=rp.id,
                    price=MoneyInputDC(
                        amount=Utils.scale_money(amt, factor),
                        currencyCode=cur,
                    ),
                ),
            )
        ff = rp.fixedFee
        if ff is None:
            return None
        amt = ff.amount
        cur = ff.currencyCode
        return MethodDefinitionInput(
            id=self.id,
            participant=DeliveryParticipantInputDC(
                id=rp.id,
                fixedFee=MoneyInputDC(
                    amount=Utils.scale_money(amt, factor),
                    currencyCode=cur,
                ),
            ),
        )

    def update_input_offset(self, delta: Decimal) -> MethodDefinitionInput | None:
        rp = self.rateProvider
        if rp is None:
            return None
        if isinstance(rp, DeliveryRateDefinitionDC):
            amt = rp.price.amount
            cur = rp.price.currencyCode
            new_amt = Utils.offset_money(amt, delta)
            return MethodDefinitionInput(
                id=self.id,
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
        new_amt = Utils.offset_money(amt, delta)
        return MethodDefinitionInput(
            id=self.id,
            participant=DeliveryParticipantInputDC(
                id=rp.id,
                fixedFee=MoneyInputDC(amount=new_amt, currencyCode=cur),
            ),
        )

    def price_pair_percent(self, factor: Decimal) -> tuple[str, str] | None:
        rp = self.rateProvider
        if rp is None:
            return None
        if isinstance(rp, DeliveryRateDefinitionDC):
            amt = rp.price.amount
            cur = rp.price.currencyCode
            new_amt = Utils.scale_money(amt, factor)
            return (
                Currency.format_amount(amt, cur),
                Currency.format_amount(new_amt, cur),
            )
        ff = rp.fixedFee
        if ff is None:
            return None
        amt = ff.amount
        cur = ff.currencyCode
        new_amt = Utils.scale_money(amt, factor)
        return (
            Currency.format_amount(amt, cur),
            Currency.format_amount(new_amt, cur),
        )

    def price_pair_offset(self, delta: Decimal) -> tuple[str, str] | None:
        rp = self.rateProvider
        if rp is None:
            return None
        if isinstance(rp, DeliveryRateDefinitionDC):
            amt = rp.price.amount
            cur = rp.price.currencyCode
            new_amt = Utils.offset_money(amt, delta)
            return (
                Currency.format_amount(amt, cur),
                Currency.format_amount(new_amt, cur),
            )
        ff = rp.fixedFee
        if ff is None:
            return None
        amt = ff.amount
        cur = ff.currencyCode
        new_amt = Utils.offset_money(amt, delta)
        return (
            Currency.format_amount(amt, cur),
            Currency.format_amount(new_amt, cur),
        )

    def format_boundary(self) -> str:
        mcs = self.methodConditions
        if not mcs or len(mcs) == 0:
            return "No tier limits"
        weight_conds = MethodConditionList(
            [c for c in mcs if c.parse_weight_triple() is not None]
        )
        money_conds = MethodConditionList(
            [c for c in mcs if c.parse_money_triple() is not None]
        )
        other = MethodConditionList([
            c for c in mcs if c not in weight_conds and c not in money_conds
        ])

        parts: list[str] = []
        w_seg = weight_conds.format_weight_segment()
        if w_seg:
            parts.append(w_seg)
        elif weight_conds:
            parts.extend(
                s
                for c in weight_conds
                if (s := c.format_condition())
            )
        m_seg = money_conds.format_money_segment()
        if m_seg:
            parts.append(m_seg)
        elif money_conds:
            parts.extend(
                s
                for c in money_conds
                if (s := c.format_condition())
            )
        for c in other:
            s = c.format_condition()
            if s:
                parts.append(s)
        if not parts:
            return "Tier conditions"
        return " · ".join(parts)



@dataclass(config=_CONFIG)
class ZoneRefDC:
    id: str
    name: str | None = None


@dataclass(config=_CONFIG)
class LocationGroupZone:
    zone: ZoneRefDC
    methodDefinitions: Connection[MethodDefinition]


@dataclass(config=_CONFIG)
class ProfileLocationGroupZoneDC:
    locationGroup: DeliveryLocationGroup
    locationGroupZones: Connection[LocationGroupZone]


@dataclass(config=_CONFIG)
class DeliveryProfileZonesRootDC:
    profileLocationGroups: list[ProfileLocationGroupZoneDC] | None = None


@dataclass(config=_CONFIG)
class DeliveryProfileQueryDataDC:
    deliveryProfile: DeliveryProfileZonesRootDC | None = None


# --- Catalog row (aggregated in app, not a single GQL type) ---


@dataclass(config=_CONFIG)
class CatalogRow:
    profileId: str
    profileName: str
    locationGroupId: str
    zoneId: str
    zoneName: str
    method: MethodDefinition

    def matches_profile_zone(self, profile_id: str | None, zone_id: str | None) -> bool:
        if profile_id is not None and self.profileId != profile_id:
            return False
        if zone_id is not None and self.zoneId != zone_id:
            return False
        return True


class CatalogRowList(list[CatalogRow]):
    def unique_rate_names(self) -> list[str]:
        names: set[str] = set[str]()
        for row in self:
            n = row.method.name
            if n:
                names.add(n)
        return sorted(names)

    def build_delivery_profile_filters(self) -> tuple[list[Json.Object], Json.Object]:
        """Unique delivery profiles and zones per profile (for filter dropdowns)."""
        profiles_map: dict[str, str] = {}
        zones_by_profile: dict[str, dict[str, str]] = defaultdict(dict)
        for row in self:
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


# --- Preview API (computed in app, matches JSON shape for /shipping-rates/preview) ---


@dataclass(config=_CONFIG)
class PreviewRateRowDC:
    id: str
    boundary: str
    current: str
    new: str


@dataclass(config=_CONFIG)
class PreviewZoneBlockDC:
    id: str
    name: str
    rows: list[PreviewRateRowDC]


@dataclass(config=_CONFIG)
class PreviewProfileBlockDC:
    id: str
    name: str
    zones: list[PreviewZoneBlockDC]


# --- delivery_profile_update.gql: variables (DeliveryProfileInput & nested inputs) ---


@dataclass(config=_CONFIG)
class MoneyInputDC:
    """Shopify ``MoneyInput`` (amount + currency) for mutation variables."""

    amount: str
    currencyCode: str


@dataclass(config=_CONFIG)
class DeliveryRateDefinitionInputDC:
    id: str
    price: MoneyInputDC


@dataclass(config=_CONFIG)
class DeliveryParticipantInputDC:
    id: str
    fixedFee: MoneyInputDC


@dataclass(config=_CONFIG)
class MethodDefinitionInput:
    """``methodDefinitionsToUpdate`` entry (rate definition vs carrier participant)."""

    id: str
    rateDefinition: DeliveryRateDefinitionInputDC | None = None
    participant: DeliveryParticipantInputDC | None = None


class MethodDefinitionInputsByZone(defaultdict[str, list[MethodDefinitionInput]]):
    """Zone id → method update inputs; ``defaultdict`` so ``[zone_id]`` yields a new list."""

    def __init__(self) -> None:
        super().__init__(list)

    def update_batches(self, mutation_cap: int) -> list[list[ZoneUpdateInputDC]]:
        """
        Split zone → method update inputs into several GraphQL mutations.

        Each zone's list is split into slices of at most ``mutation_cap``,
        then slices are packed into batches so each batch has at most that many updates total
        (multiple zones may share one mutation when they fit).
        """
        pieces: list[tuple[str, list[MethodDefinitionInput]]] = []
        for zone_id, methods in self.items():
            for chunk in Utils.chunks(methods, mutation_cap):
                pieces.append((zone_id, chunk))
        batches: list[list[ZoneUpdateInputDC]] = []
        cur: list[ZoneUpdateInputDC] = []
        cur_total = 0
        for zid, mets in pieces:
            n = len(mets)
            if cur_total + n > mutation_cap and cur:
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


class MethodDefinitionInputsByLocationGroup(defaultdict[str, MethodDefinitionInputsByZone]):
    """Location group id → :class:`MethodDefinitionInputsByZone` (nested ``defaultdict``)."""

    def __init__(self) -> None:
        super().__init__(lambda: MethodDefinitionInputsByZone())


class MethodDefinitionInputsByProfile(defaultdict[str, MethodDefinitionInputsByLocationGroup]):
    """
    Profile id → location group id → :class:`MethodDefinitionInputsByZone`
    (nested ``defaultdict``).
    """

    def __init__(self) -> None:
        super().__init__(lambda: MethodDefinitionInputsByLocationGroup())

    def update_by_name_percent(
        self,
        rows: CatalogRowList,
        warnings: list[str],
        rate_name: str,
        percent: float,
        profile_id: str | None = None,
        zone_id: str | None = None,
        adjustment_mode: Literal["percent", "offset"] = "percent"
    ) -> tuple[int, list[str]]:
        factor: Decimal | None = None
        amount_delta: Decimal | None = None
        if adjustment_mode == "percent":
            factor = Decimal(1) + Decimal(str(percent)) / Decimal(100)
        else:
            amount_delta = Decimal(str(percent))
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
            self[pid][lg][zid].append(inp)
            updated += 1
        return updated, warnings


@dataclass(config=_CONFIG)
class ZoneUpdateInputDC:
    id: str
    methodDefinitionsToUpdate: list[MethodDefinitionInput]


@dataclass(config=_CONFIG)
class DeliveryProfileLocationGroupInputDC:
    id: str
    zonesToUpdate: list[ZoneUpdateInputDC]


@dataclass(config=_CONFIG)
class DeliveryProfileInputDC:
    locationGroupsToUpdate: list[DeliveryProfileLocationGroupInputDC]


@dataclass(config=_CONFIG)
class DeliveryProfileUpdateVariablesDC(Jsonable):
    """Variables for ``DeliveryProfileUpdate`` (``$id``, ``$profile``)."""

    id: str
    profile: DeliveryProfileInputDC


# --- delivery_profile_update.gql: response ---


@dataclass(config=_CONFIG)
class UserErrorDC:
    field: list[str] | None = None
    message: str | None = None


@dataclass(config=_CONFIG)
class DeliveryProfileUpdatePayloadDC:
    userErrors: list[UserErrorDC]


@dataclass(config=_CONFIG)
class DeliveryProfileUpdateDataDC:
    deliveryProfileUpdate: DeliveryProfileUpdatePayloadDC | None = None
