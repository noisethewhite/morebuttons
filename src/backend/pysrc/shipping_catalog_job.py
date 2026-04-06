from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import cast

from .fileloader import FileLoader
from .graphql import GraphQL
from .web_types import Json
from .graphqldc.shipping import (
    CatalogRow,
    CatalogRowList,
    DeliveryProfileQueryData,
    DeliveryProfilesQueryData,
)


@dataclass
class ShippingCatalogJob:
    """One GraphQL call per step(); drives delivery profile + zone pagination."""

    id: str
    shop_domain: str
    token: str
    rows: CatalogRowList = field(default_factory=CatalogRowList)
    warnings: list[str] = field(default_factory=list)

    _q_profiles: str = field(init=False)
    _q_zones: str = field(init=False)

    after_profiles: str | None = None
    profiles_exhausted: bool = False
    zone_queue: deque[tuple[str, str, str, str | None]] = field(
        default_factory=deque
    )
    completed_steps: int = 0

    def __post_init__(self) -> None:
        self._q_profiles = FileLoader.load("delivery_profiles_page.gql")
        self._q_zones = FileLoader.load("delivery_profile_group_zones.gql")

    def _estimate_remaining(self) -> int:
        n = len(self.zone_queue)
        if not self.profiles_exhausted:
            n += 1
        return max(n, 0)

    def step(self) -> Json.Object:
        """
        Run one Shopify GraphQL request. Returns a dict with done, payload keys, and
        progress fields for headers (completed, remaining, total).
        """
        self.completed_steps += 1
        if not self.profiles_exhausted:
            return self._step_profiles()
        if self.zone_queue:
            return self._step_zones()
        return self._finish()

    def _step_profiles(self) -> Json.Object:
        parsed = GraphQL.send(
            self.shop_domain,
            self.token,
            self._q_profiles,
            {"first": 50, "after": self.after_profiles},
            expected_type=DeliveryProfilesQueryData,
        )
        if parsed is None:
            self.warnings.append(
                "Unexpected response shape from deliveryProfiles query " + \
                "(internal validation failed)."
            )
            self.profiles_exhausted = True
            rem = self._estimate_remaining()
            return {
                "done": False,
                "completed": self.completed_steps,
                "remaining": rem,
                "total": self.completed_steps + rem,
                "phase": "shipping_catalog",
            }

        conn = parsed.deliveryProfiles
        for edge in conn.edges:
            node_p = edge.node
            pid = node_p.id
            pname = node_p.name or ""
            plgs = node_p.profileLocationGroups or []
            for plg in plgs:
                lg_id = plg.locationGroup.id
                self.zone_queue.append((pid, pname, lg_id, None))

        nxt = conn.pageInfo.next_page_cursor()
        if nxt is None:
            self.profiles_exhausted = True
            self.after_profiles = None
        else:
            self.after_profiles = nxt

        rem = self._estimate_remaining()
        out: Json.Object = {
            "done": False,
            "completed": self.completed_steps,
            "remaining": rem,
            "total": self.completed_steps + rem,
            "phase": "shipping_catalog",
        }
        if self.profiles_exhausted and not self.zone_queue:
            return self._finish()
        return out

    def _step_zones(self) -> Json.Object:
        pid, pname, lg_id, after_zones = self.zone_queue.popleft()
        parsed = GraphQL.send(
            self.shop_domain,
            self.token,
            self._q_zones,
            {
                "profileId": pid,
                "locationGroupId": lg_id,
                "zonesFirst": 50,
                "zonesAfter": after_zones,
            },
            expected_type=DeliveryProfileQueryData,
        )
        if parsed is None:
            self.warnings.append(
                "Unexpected response shape from deliveryProfile query " + \
                "(internal validation failed)."
            )
            rem = self._estimate_remaining()
            done = self.profiles_exhausted and not self.zone_queue
            if done:
                return self._finish()
            return {
                "done": False,
                "completed": self.completed_steps,
                "remaining": rem,
                "total": self.completed_steps + rem,
                "phase": "shipping_catalog",
            }

        dp = parsed.deliveryProfile
        if not dp or not dp.profileLocationGroups:
            self.warnings.append(
                f"Missing delivery profile data for profile {pid} (location group {lg_id})."
            )
            rem = self._estimate_remaining()
            done = self.profiles_exhausted and not self.zone_queue
            if done:
                return self._finish()
            return {
                "done": False,
                "completed": self.completed_steps,
                "remaining": rem,
                "total": self.completed_steps + rem,
                "phase": "shipping_catalog",
            }

        plg0 = dp.profileLocationGroups[0]
        zconn = plg0.locationGroupZones
        for zedge in zconn.edges:
            zn = zedge.node
            zone = zn.zone
            zid = zone.id
            zname = zone.name or ""
            md = zn.methodDefinitions
            if md.pageInfo.hasNextPage is True:
                self.warnings.append(
                    f"More than 250 method definitions in a zone; " + \
                    f"only the first page was loaded (zone {zid})."
                )
            for medge in md.edges:
                mnode = medge.node
                self.rows.append(
                    CatalogRow(
                        profileId=pid,
                        profileName=pname,
                        locationGroupId=lg_id,
                        zoneId=zid,
                        zoneName=zname,
                        method=mnode,
                    )
                )

        nxt = zconn.pageInfo.next_page_cursor()
        if nxt is not None:
            self.zone_queue.appendleft((pid, pname, lg_id, nxt))

        rem = self._estimate_remaining()
        done = self.profiles_exhausted and not self.zone_queue
        out = cast(Json.Object, {
            "done": done,
            "completed": self.completed_steps,
            "remaining": rem,
            "total": self.completed_steps + rem,
            "phase": "shipping_catalog",
        })
        if done:
            return self._finish()
        return out

    def _finish(self) -> Json.Object:
        from .catalog_cache import set_shipping_catalog

        set_shipping_catalog(self.shop_domain, self.rows, self.warnings)
        names = self.rows.unique_rate_names()
        filters = self.rows.build_delivery_profile_filters()
        return cast(Json.Object, {
            "done": True,
            "completed": self.completed_steps,
            "remaining": 0,
            "total": self.completed_steps,
            "phase": "shipping_catalog",
            "names": names,
            **filters.to_json(),
            "warnings": self.warnings,
        })


_JOBS: dict[str, ShippingCatalogJob] = {}


def create_shipping_catalog_job(shop_domain: str, token: str) -> str:
    jid = uuid.uuid4().hex
    _JOBS[jid] = ShippingCatalogJob(id=jid, shop_domain=shop_domain, token=token)
    return jid


def take_shipping_catalog_job(job_id: str) -> ShippingCatalogJob | None:
    return _JOBS.get(job_id)


def delete_shipping_catalog_job(job_id: str) -> None:
    _ = _JOBS.pop(job_id, None)
