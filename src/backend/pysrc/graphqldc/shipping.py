from __future__ import annotations

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass
from decimal import Decimal
from .common import Connection, Jsonable
from ..utils import Utils
from ..symbols import Currency


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
class MethodConditionDC:
    field: str | None = None
    operator: str | None = None
    conditionCriteria: WeightCriteriaDC | MoneyV2CriteriaDC | None = None


@dataclass(config=_CONFIG)
class MethodDefinition:
    id: str
    name: str | None = None
    methodConditions: list[MethodConditionDC] | None = None
    rateProvider: DeliveryRateDefinitionDC | DeliveryParticipantDC | None = None

    def update_input_percent(self, factor: Decimal) -> MethodDefinitionUpdateInputDC | None:
        rp = self.rateProvider
        if rp is None:
            return None
        if isinstance(rp, DeliveryRateDefinitionDC):
            amt = rp.price.amount
            cur = rp.price.currencyCode
            return MethodDefinitionUpdateInputDC(
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
        return MethodDefinitionUpdateInputDC(
            id=self.id,
            participant=DeliveryParticipantInputDC(
                id=rp.id,
                fixedFee=MoneyInputDC(
                    amount=Utils.scale_money(amt, factor),
                    currencyCode=cur,
                ),
            ),
        )

    def update_input_offset(self, delta: Decimal) -> MethodDefinitionUpdateInputDC | None:
        rp = self.rateProvider
        if rp is None:
            return None
        if isinstance(rp, DeliveryRateDefinitionDC):
            amt = rp.price.amount
            cur = rp.price.currencyCode
            new_amt = Utils.offset_money(amt, delta)
            return MethodDefinitionUpdateInputDC(
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
        return MethodDefinitionUpdateInputDC(
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
class CatalogRowDC:
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
class MethodDefinitionUpdateInputDC:
    """``methodDefinitionsToUpdate`` entry (rate definition vs carrier participant)."""

    id: str
    rateDefinition: DeliveryRateDefinitionInputDC | None = None
    participant: DeliveryParticipantInputDC | None = None


@dataclass(config=_CONFIG)
class ZoneUpdateInputDC:
    id: str
    methodDefinitionsToUpdate: list[MethodDefinitionUpdateInputDC]


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
