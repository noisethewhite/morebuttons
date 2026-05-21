from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from .catalog_cache import get_sku_weight_catalog, invalidate_sku_weight_catalog
from .fileloader import FileLoader
from .graphql import GraphQL
from .graphqldc.products import (
    InventoryItemMeasurementInput,
    InventoryItemWeightInput,
    ProductVariantsBulkUpdateData,
    SkuWeightApplyStepDone,
    SkuWeightApplyStepPending,
    SkuWeightApplyStepResult,
    VariantWeightBulkInputRow,
    VariantWeightBulkUpdateVariables,
    WeightInput,
)


@dataclass
class SkuWeightApplyJob:
    id: str
    shop_domain: str
    token: str
    target_g: float
    # (product_id, [variant_id, ...]) — one entry per product, consumed in order
    tasks: list[tuple[str, list[str]]]
    warnings: list[str] = field(default_factory=list)
    user_msgs: list[str] = field(default_factory=list)
    completed: int = 0
    updated: int = 0
    _mut: str = field(init=False)

    def __post_init__(self) -> None:
        self._mut = FileLoader.load("product_variants_weight_update.gql")

    def step(self) -> SkuWeightApplyStepResult:
        if not self.tasks:
            return self._finish()

        product_id, variant_ids = self.tasks.pop(0)
        weight_input = WeightInput(value=self.target_g, unit="GRAMS")
        variants = [
            VariantWeightBulkInputRow(
                id=vid,
                inventoryItem=InventoryItemWeightInput(
                    measurement=InventoryItemMeasurementInput(weight=weight_input)
                ),
            )
            for vid in variant_ids
        ]
        variables = VariantWeightBulkUpdateVariables(
            productId=product_id, variants=variants
        )
        parsed, soft_errs = GraphQL.send(
            self.shop_domain,
            self.token,
            self._mut,
            variables.to_json(),
            expected_type=ProductVariantsBulkUpdateData,
            raise_on_graphql_error=False,
        )
        self.completed += 1

        if parsed is None:
            self.user_msgs.extend(soft_errs)
        else:
            payload = parsed.productVariantsBulkUpdate
            if payload is None:
                self.user_msgs.append(
                    f"Product {product_id}: missing productVariantsBulkUpdate."
                )
            elif not payload.mutation_succeeded():
                self.user_msgs.extend(payload.user_error_messages())
            else:
                self.updated += len(variant_ids)

        if not self.tasks:
            return self._finish()

        rem = len(self.tasks)
        return SkuWeightApplyStepPending(
            completed=self.completed,
            remaining=rem,
            total=self.completed + rem,
        )

    def _finish(self) -> SkuWeightApplyStepDone:
        return SkuWeightApplyStepDone(
            completed=self.completed,
            total=self.completed,
            updated=self.updated,
            warnings=list(self.warnings),
            userErrors=list(self.user_msgs),
        )


_APPLY_JOBS: dict[str, SkuWeightApplyJob] = {}


def create_sku_weight_apply_job(
    shop_domain: str, token: str, pattern: str, target_g: float
) -> str:
    cached = get_sku_weight_catalog(shop_domain, pattern)
    if cached is None:
        raise RuntimeError("SKU weight catalog for this pattern is not loaded.")
    rows, warnings = cached

    by_product: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        by_product[r.productId].append(r.variantId)

    tasks = list(by_product.items())
    invalidate_sku_weight_catalog(shop_domain, pattern)

    jid = uuid.uuid4().hex
    _APPLY_JOBS[jid] = SkuWeightApplyJob(
        id=jid,
        shop_domain=shop_domain,
        token=token,
        target_g=target_g,
        tasks=tasks,
        warnings=list(warnings),
    )
    return jid


def take_sku_weight_apply_job(job_id: str) -> SkuWeightApplyJob | None:
    return _APPLY_JOBS.get(job_id)


def delete_sku_weight_apply_job(job_id: str) -> None:
    _ = _APPLY_JOBS.pop(job_id, None)
