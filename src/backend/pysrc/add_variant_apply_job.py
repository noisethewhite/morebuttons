from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .catalog_cache import get_add_variant_catalog, invalidate_add_variant_catalog
from .fileloader import FileLoader
from .graphql import GraphQL
from .graphqldc.products import (
    AddVariantApplyStepDone,
    AddVariantApplyStepPending,
    AddVariantApplyStepResult,
    InventoryItemMeasurementInput,
    InventoryItemWeightInput,
    ProductVariantsBulkCreateData,
    VariantBulkCreateInputRow,
    VariantBulkCreateVariables,
    VariantOptionValueInput,
    WeightInput,
)


@dataclass
class AddVariantApplyJob:
    id: str
    shop_domain: str
    token: str
    option_value: str
    weight_g: float
    price: str
    # (productId, firstOptionName, newSku)
    tasks: list[tuple[str, str, str]]
    warnings: list[str] = field(default_factory=list)
    user_msgs: list[str] = field(default_factory=list)
    completed: int = 0
    updated: int = 0
    _mut: str = field(init=False)

    def __post_init__(self) -> None:
        self._mut = FileLoader.load("product_variants_bulk_create.gql")

    def step(self) -> AddVariantApplyStepResult:
        if not self.tasks:
            return self._finish()

        product_id, option_name, new_sku = self.tasks.pop(0)
        variant = VariantBulkCreateInputRow(
            price=self.price,
            optionValues=[VariantOptionValueInput(optionName=option_name, name=self.option_value)],
            inventoryItem=InventoryItemWeightInput(
                measurement=InventoryItemMeasurementInput(
                    weight=WeightInput(value=self.weight_g, unit="GRAMS")
                ),
                sku=new_sku,
            ),
        )
        variables = VariantBulkCreateVariables(productId=product_id, variants=[variant])
        parsed, soft_errs = GraphQL.send(
            self.shop_domain,
            self.token,
            self._mut,
            variables.to_json(),
            expected_type=ProductVariantsBulkCreateData,
            raise_on_graphql_error=False,
        )
        self.completed += 1

        if parsed is None:
            self.user_msgs.extend(soft_errs)
        else:
            payload = parsed.productVariantsBulkCreate
            if payload is None:
                self.user_msgs.append(
                    f"Product {product_id}: missing productVariantsBulkCreate."
                )
            elif not payload.mutation_succeeded():
                self.user_msgs.extend(payload.user_error_messages())
            else:
                self.updated += 1

        if not self.tasks:
            return self._finish()

        rem = len(self.tasks)
        return AddVariantApplyStepPending(
            completed=self.completed,
            remaining=rem,
            total=self.completed + rem,
        )

    def _finish(self) -> AddVariantApplyStepDone:
        return AddVariantApplyStepDone(
            completed=self.completed,
            total=self.completed,
            updated=self.updated,
            warnings=list(self.warnings),
            userErrors=list(self.user_msgs),
        )


_APPLY_JOBS: dict[str, AddVariantApplyJob] = {}


def create_add_variant_apply_job(
    shop_domain: str,
    token: str,
    pattern: str,
    suffix: str,
    option_value: str,
    weight_g: float,
    price: str,
) -> str:
    cached = get_add_variant_catalog(shop_domain, pattern)
    if cached is None:
        raise RuntimeError("Add variant catalog for this pattern is not loaded.")
    rows, warnings = cached

    tasks = [
        (row.productId, row.firstOptionName, f"{row.baseSkuPrefix}-{suffix}")
        for row in rows
    ]
    invalidate_add_variant_catalog(shop_domain, pattern)

    jid = uuid.uuid4().hex
    _APPLY_JOBS[jid] = AddVariantApplyJob(
        id=jid,
        shop_domain=shop_domain,
        token=token,
        option_value=option_value,
        weight_g=weight_g,
        price=price,
        tasks=tasks,
        warnings=list(warnings),
    )
    return jid


def take_add_variant_apply_job(job_id: str) -> AddVariantApplyJob | None:
    return _APPLY_JOBS.get(job_id)


def delete_add_variant_apply_job(job_id: str) -> None:
    _ = _APPLY_JOBS.pop(job_id, None)
