from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from .catalog_cache import set_sku_weight_catalog
from .fileloader import FileLoader
from .graphql import GraphQL
from .graphqldc.products import (
    ProductsSkuWeightQueryData,
    SkuWeightCatalogStepDone,
    SkuWeightCatalogStepPending,
    SkuWeightCatalogStepResult,
    SkuWeightVariantRow,
)

_KG = 1000.0
_OZ = 28.3495
_LB = 453.592


def _to_grams(value: float, unit: str) -> float:
    match unit.upper():
        case "GRAMS" | "G":
            return value
        case "KILOGRAMS" | "KG":
            return value * _KG
        case "OUNCES" | "OZ":
            return value * _OZ
        case "POUNDS" | "LB" | "LBS":
            return value * _LB
        case _:
            return value


@dataclass
class SkuWeightCatalogJob:
    id: str
    shop_domain: str
    token: str
    pattern: str
    rows: list[SkuWeightVariantRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    after: str | None = None
    exhausted: bool = False
    completed_steps: int = 0
    _compiled: re.Pattern | None = field(init=False)
    _query: str = field(init=False)

    def __post_init__(self) -> None:
        self._query = FileLoader.load("products_sku_weight_page.gql")
        try:
            self._compiled = re.compile(self.pattern, re.IGNORECASE)
        except re.error as e:
            self._compiled = None
            self.warnings.append(f"Invalid regex pattern: {e}")
            self.exhausted = True

    def _estimate_remaining(self) -> int:
        return 0 if self.exhausted else 1

    def step(self) -> SkuWeightCatalogStepResult:
        self.completed_steps += 1
        if self.exhausted:
            return self._finish()
        return self._step_products()

    def _step_products(self) -> SkuWeightCatalogStepResult:
        compiled = self._compiled
        if compiled is None:
            self.exhausted = True
            return self._finish()

        try:
            parsed = GraphQL.send(
                self.shop_domain,
                self.token,
                self._query,
                {"first": 50, "after": self.after},
                expected_type=ProductsSkuWeightQueryData,
            )
        except RuntimeError as e:
            self.warnings.append(str(e))
            self.exhausted = True
            return self._finish()

        if parsed is None:
            self.warnings.append("Unexpected response from products query.")
            self.exhausted = True
            return self._finish()

        for edge in parsed.products.edges:
            prod = edge.node
            pid = prod.id
            ptitle = prod.title or ""
            if not prod.variants:
                continue
            if prod.variants.pageInfo.hasNextPage is True:
                self.warnings.append(
                    f'Product "{ptitle}" has more than 100 variants; '
                    "only the first page was loaded."
                )
            for ve in prod.variants.edges:
                v = ve.node
                sku = (v.sku or "").strip()
                if not sku or not compiled.search(sku):
                    continue
                weight_g: float | None = None
                inv = v.inventoryItem
                if inv and inv.measurement and inv.measurement.weight:
                    w = inv.measurement.weight
                    weight_g = _to_grams(w.value, w.unit)
                self.rows.append(SkuWeightVariantRow(
                    productId=pid,
                    productTitle=ptitle,
                    variantId=v.id,
                    variantTitle=(v.title or "").strip(),
                    sku=sku,
                    weightGrams=weight_g,
                ))

        nxt = parsed.products.pageInfo.next_page_cursor()
        if nxt is None:
            self.exhausted = True
        else:
            self.after = nxt

        if self.exhausted:
            return self._finish()
        rem = self._estimate_remaining()
        return SkuWeightCatalogStepPending(
            completed=self.completed_steps,
            remaining=rem,
            total=self.completed_steps + rem,
        )

    def _finish(self) -> SkuWeightCatalogStepDone:
        set_sku_weight_catalog(self.shop_domain, self.pattern, self.rows, self.warnings)
        return SkuWeightCatalogStepDone(
            completed=self.completed_steps,
            total=self.completed_steps,
            pattern=self.pattern,
            variantCount=len(self.rows),
            warnings=list(self.warnings),
        )


_JOBS: dict[str, SkuWeightCatalogJob] = {}


def create_sku_weight_catalog_job(shop_domain: str, token: str, pattern: str) -> str:
    jid = uuid.uuid4().hex
    _JOBS[jid] = SkuWeightCatalogJob(
        id=jid, shop_domain=shop_domain, token=token, pattern=pattern
    )
    return jid


def take_sku_weight_catalog_job(job_id: str) -> SkuWeightCatalogJob | None:
    return _JOBS.get(job_id)


def delete_sku_weight_catalog_job(job_id: str) -> None:
    _ = _JOBS.pop(job_id, None)
