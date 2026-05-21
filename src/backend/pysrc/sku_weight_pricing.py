from __future__ import annotations

from .catalog_cache import get_sku_weight_catalog
from .graphqldc.products import SkuWeightPreviewRow


def preview_sku_weight_changes(
    shop_domain: str,
    pattern: str,
    target_g: float,
) -> tuple[list[SkuWeightPreviewRow], list[str]]:
    cached = get_sku_weight_catalog(shop_domain, pattern)
    if cached is None:
        raise RuntimeError(
            "SKU weight catalog for this pattern is not loaded. "
            "Wait for loading to finish."
        )
    rows, warnings = cached
    preview_rows = sorted(
        (r.to_preview_row(target_g) for r in rows),
        key=lambda r: r.sku.lower(),
    )
    return preview_rows, list(warnings)
