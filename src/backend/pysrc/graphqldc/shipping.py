from __future__ import annotations

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass
from .common import ConnectionDC


_CONFIG = ConfigDict(extra="ignore")


# --- delivery_profiles_page.gql ---


@dataclass(config=_CONFIG)
class LocationGroupRefDC(object):
    id: str


@dataclass(config=_CONFIG)
class ProfileLocationGroupListDC(object):
    locationGroup: LocationGroupRefDC


@dataclass(config=_CONFIG)
class DeliveryProfileListNodeDC(object):
    id: str
    name: str | None = None
    profileLocationGroups: list[ProfileLocationGroupListDC] | None = None


@dataclass(config=_CONFIG)
class DeliveryProfilesQueryDataDC(object):
    deliveryProfiles: ConnectionDC[DeliveryProfileListNodeDC]


# --- delivery_profile_group_zones.gql (method node + mutation payload) ---


@dataclass(config=_CONFIG)
class MoneyAmountDC(object):
    amount: str
    currencyCode: str


@dataclass(config=_CONFIG)
class DeliveryRateDefinitionDC(object):
    # JSON key is ``__typename``; avoid leading ``__`` (dataclass name-mangling).
    # Required fields before ``Field`` so stdlib dataclass ordering rules are satisfied.
    id: str
    price: MoneyAmountDC


@dataclass(config=_CONFIG)
class DeliveryParticipantDC(object):
    id: str
    fixedFee: MoneyAmountDC | None = None
    percentageOfRateFee: str | float | None = None


@dataclass(config=_CONFIG)
class WeightCriteriaDC(object):
    unit: str
    value: str | float | int | None = None


@dataclass(config=_CONFIG)
class MoneyV2CriteriaDC(object):
    amount: str
    currencyCode: str


@dataclass(config=_CONFIG)
class MethodConditionDC(object):
    field: str | None = None
    operator: str | None = None
    conditionCriteria: WeightCriteriaDC | MoneyV2CriteriaDC | None = None


@dataclass(config=_CONFIG)
class MethodDefinitionNodeDC(object):
    id: str
    name: str | None = None
    methodConditions: list[MethodConditionDC] | None = None
    rateProvider: DeliveryRateDefinitionDC | DeliveryParticipantDC | None = None


@dataclass(config=_CONFIG)
class ZoneRefDC(object):
    id: str
    name: str | None = None


@dataclass(config=_CONFIG)
class LocationGroupZoneNodeDC(object):
    zone: ZoneRefDC
    methodDefinitions: ConnectionDC[MethodDefinitionNodeDC]


@dataclass(config=_CONFIG)
class ProfileLocationGroupZoneDC(object):
    locationGroup: LocationGroupRefDC
    locationGroupZones: ConnectionDC[LocationGroupZoneNodeDC]


@dataclass(config=_CONFIG)
class DeliveryProfileZonesRootDC(object):
    profileLocationGroups: list[ProfileLocationGroupZoneDC] | None = None


@dataclass(config=_CONFIG)
class DeliveryProfileQueryDataDC(object):
    deliveryProfile: DeliveryProfileZonesRootDC | None = None


# --- Catalog row (aggregated in app, not a single GQL type) ---


@dataclass(config=_CONFIG)
class CatalogRowDC(object):
    profileId: str
    profileName: str
    locationGroupId: str
    zoneId: str
    zoneName: str
    method: MethodDefinitionNodeDC


# --- Preview API (computed in app, matches JSON shape for /shipping-rates/preview) ---


@dataclass(config=_CONFIG)
class PreviewRateRowDC(object):
    id: str
    boundary: str
    current: str
    new: str


@dataclass(config=_CONFIG)
class PreviewZoneBlockDC(object):
    id: str
    name: str
    rows: list[PreviewRateRowDC]


@dataclass(config=_CONFIG)
class PreviewProfileBlockDC(object):
    id: str
    name: str
    zones: list[PreviewZoneBlockDC]


# --- delivery_profile_update.gql: variables (DeliveryProfileInput & nested inputs) ---


@dataclass(config=_CONFIG)
class MoneyInputDC(object):
    """Shopify ``MoneyInput`` (amount + currency) for mutation variables."""

    amount: str
    currencyCode: str


@dataclass(config=_CONFIG)
class DeliveryRateDefinitionInputDC(object):
    id: str
    price: MoneyInputDC


@dataclass(config=_CONFIG)
class DeliveryParticipantInputDC(object):
    id: str
    fixedFee: MoneyInputDC


@dataclass(config=_CONFIG)
class MethodDefinitionUpdateInputDC(object):
    """``methodDefinitionsToUpdate`` entry (rate definition vs carrier participant)."""

    id: str
    rateDefinition: DeliveryRateDefinitionInputDC | None = None
    participant: DeliveryParticipantInputDC | None = None


@dataclass(config=_CONFIG)
class ZoneUpdateInputDC(object):
    id: str
    methodDefinitionsToUpdate: list[MethodDefinitionUpdateInputDC]


@dataclass(config=_CONFIG)
class DeliveryProfileLocationGroupInputDC(object):
    id: str
    zonesToUpdate: list[ZoneUpdateInputDC]


@dataclass(config=_CONFIG)
class DeliveryProfileInputDC(object):
    locationGroupsToUpdate: list[DeliveryProfileLocationGroupInputDC]


@dataclass(config=_CONFIG)
class DeliveryProfileUpdateVariablesDC(object):
    """Variables for ``DeliveryProfileUpdate`` (``$id``, ``$profile``)."""

    id: str
    profile: DeliveryProfileInputDC


# --- delivery_profile_update.gql: response ---


@dataclass(config=_CONFIG)
class UserErrorDC(object):
    field: list[str] | None = None
    message: str | None = None


@dataclass(config=_CONFIG)
class DeliveryProfileUpdatePayloadDC(object):
    userErrors: list[UserErrorDC]


@dataclass(config=_CONFIG)
class DeliveryProfileUpdateDataDC(object):
    deliveryProfileUpdate: DeliveryProfileUpdatePayloadDC | None = None
