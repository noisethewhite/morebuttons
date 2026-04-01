from __future__ import annotations

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from .common import EdgeDC, PageInfoDC


# --- delivery_profiles_page.gql ---


@dataclass(config=ConfigDict(extra="ignore"))
class LocationGroupRefDC(object):
    id: str


@dataclass(config=ConfigDict(extra="ignore"))
class ProfileLocationGroupListDC(object):
    locationGroup: LocationGroupRefDC


@dataclass(config=ConfigDict(extra="ignore"))
class DeliveryProfileListNodeDC(object):
    id: str
    name: str | None = None
    profileLocationGroups: list[ProfileLocationGroupListDC] | None = None


@dataclass(config=ConfigDict(extra="ignore"))
class DeliveryProfilesConnectionDC(object):
    edges: list[EdgeDC[DeliveryProfileListNodeDC]]
    pageInfo: PageInfoDC


@dataclass(config=ConfigDict(extra="ignore"))
class DeliveryProfilesQueryDataDC(object):
    deliveryProfiles: DeliveryProfilesConnectionDC


# --- delivery_profile_group_zones.gql (method node + mutation payload) ---


@dataclass(config=ConfigDict(extra="ignore"))
class MoneyAmountDC(object):
    amount: str
    currencyCode: str


@dataclass(config=ConfigDict(extra="ignore"))
class DeliveryRateDefinitionDC(object):
    # JSON key is ``__typename``; avoid leading ``__`` (dataclass name-mangling).
    # Required fields before ``Field`` so stdlib dataclass ordering rules are satisfied.
    id: str
    price: MoneyAmountDC


@dataclass(config=ConfigDict(extra="ignore"))
class DeliveryParticipantDC(object):
    id: str
    fixedFee: MoneyAmountDC | None = None
    percentageOfRateFee: str | float | None = None


@dataclass(config=ConfigDict(extra="ignore"))
class WeightCriteriaDC(object):
    unit: str
    value: str | float | int | None = None


@dataclass(config=ConfigDict(extra="ignore"))
class MoneyV2CriteriaDC(object):
    amount: str
    currencyCode: str


@dataclass(config=ConfigDict(extra="ignore"))
class MethodConditionDC(object):
    field: str | None = None
    operator: str | None = None
    conditionCriteria: WeightCriteriaDC | MoneyV2CriteriaDC | None = None


@dataclass(config=ConfigDict(extra="ignore"))
class MethodDefinitionNodeDC(object):
    id: str
    name: str | None = None
    methodConditions: list[MethodConditionDC] | None = None
    rateProvider: DeliveryRateDefinitionDC | DeliveryParticipantDC | None = None


@dataclass(config=ConfigDict(extra="ignore"))
class MethodDefinitionConnectionDC(object):
    edges: list[EdgeDC[MethodDefinitionNodeDC]]
    pageInfo: PageInfoDC


@dataclass(config=ConfigDict(extra="ignore"))
class ZoneRefDC(object):
    id: str
    name: str | None = None


@dataclass(config=ConfigDict(extra="ignore"))
class LocationGroupZoneNodeDC(object):
    zone: ZoneRefDC
    methodDefinitions: MethodDefinitionConnectionDC


@dataclass(config=ConfigDict(extra="ignore"))
class LocationGroupZonesConnectionDC(object):
    edges: list[EdgeDC[LocationGroupZoneNodeDC]]
    pageInfo: PageInfoDC


@dataclass(config=ConfigDict(extra="ignore"))
class ProfileLocationGroupZoneDC(object):
    locationGroup: LocationGroupRefDC
    locationGroupZones: LocationGroupZonesConnectionDC


@dataclass(config=ConfigDict(extra="ignore"))
class DeliveryProfileZonesRootDC(object):
    profileLocationGroups: list[ProfileLocationGroupZoneDC] | None = None


@dataclass(config=ConfigDict(extra="ignore"))
class DeliveryProfileQueryDataDC(object):
    deliveryProfile: DeliveryProfileZonesRootDC | None = None


# --- Catalog row (aggregated in app, not a single GQL type) ---


@dataclass(config=ConfigDict(extra="ignore"))
class CatalogRowDC(object):
    profileId: str
    profileName: str
    locationGroupId: str
    zoneId: str
    zoneName: str
    method: MethodDefinitionNodeDC


# --- delivery_profile_update.gql ---


@dataclass(config=ConfigDict(extra="ignore"))
class UserErrorDC(object):
    field: list[str] | None = None
    message: str | None = None


@dataclass(config=ConfigDict(extra="ignore"))
class DeliveryProfileUpdatePayloadDC(object):
    userErrors: list[UserErrorDC]


@dataclass(config=ConfigDict(extra="ignore"))
class DeliveryProfileUpdateDataDC(object):
    deliveryProfileUpdate: DeliveryProfileUpdatePayloadDC | None = None
