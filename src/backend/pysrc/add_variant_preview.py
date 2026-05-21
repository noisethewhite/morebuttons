from __future__ import annotations

from .catalog_cache import get_add_variant_catalog
from .graphqldc.products import AddVariantPreviewRow


def preview_add_variant(
    shop_domain: str,
    pattern: str,
    suffix: str,
    option_value: str,
    weight_g: float,
    price: str,
) -> tuple[list[AddVariantPreviewRow], list[str]]:
    cached = get_add_variant_catalog(shop_domain, pattern)
    if cached is None:
        raise RuntimeError(
            "Add variant catalog for this pattern is not loaded. "
            "Wait for loading to finish."
        )
    rows, warnings = cached

    conflicts: list[str] = []
    for row in rows:
        new_sku = f"{row.baseSkuPrefix}-{suffix}"
        if new_sku in row.allVariantSkus:
            conflicts.append(f"{row.productTitle} ({new_sku})")

    if conflicts:
        n = len(conflicts)
        noun = "product" if n == 1 else "products"
        verb = "has" if n == 1 else "have"
        sample = ", ".join(conflicts[:5]) + ("…" if len(conflicts) > 5 else "")
        raise ValueError(
            f"{n} {noun} already {verb} a variant with the target SKU: {sample}"
        )

    preview_rows = sorted(
        [
            AddVariantPreviewRow(
                productId=row.productId,
                productTitle=row.productTitle,
                newSku=f"{row.baseSkuPrefix}-{suffix}",
                optionValue=option_value,
                weightGrams=weight_g,
                price=price,
            )
            for row in rows
        ],
        key=lambda r: r.productTitle.lower(),
    )
    return preview_rows, list(warnings)
