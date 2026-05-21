from __future__ import annotations

from .graphqldc.products import AddVariantCatalogRow, SkuWeightVariantRow, TaggedVariantRow
from .graphqldc.shipping import CatalogRowList

_shipping_catalog: dict[str, tuple[CatalogRowList, list[str]]] = {}
_tagged_variants: dict[str, tuple[list[TaggedVariantRow], list[str]]] = {}


def _tag_key(shop_domain: str, tag: str) -> str:
    return f"{shop_domain}\n{tag.strip()}"


def get_shipping_catalog(shop_domain: str) -> tuple[CatalogRowList, list[str]] | None:
    return _shipping_catalog.get(shop_domain)


def set_shipping_catalog(
    shop_domain: str,
    rows: CatalogRowList,
    warnings: list[str],
) -> None:
    _shipping_catalog[shop_domain] = (rows, list(warnings))


def invalidate_shipping_catalog(shop_domain: str) -> None:
    _ = _shipping_catalog.pop(shop_domain, None)


def get_tagged_variants_catalog(
    shop_domain: str, tag: str
) -> tuple[list[TaggedVariantRow], list[str]] | None:
    return _tagged_variants.get(_tag_key(shop_domain, tag))


def set_tagged_variants_catalog(
    shop_domain: str,
    tag: str,
    rows: list[TaggedVariantRow],
    warnings: list[str],
) -> None:
    _tagged_variants[_tag_key(shop_domain, tag)] = (rows, list(warnings))


def invalidate_tagged_variants_catalog(shop_domain: str, tag: str) -> None:
    _ = _tagged_variants.pop(_tag_key(shop_domain, tag), None)


_sku_weight_catalog: dict[str, tuple[list[SkuWeightVariantRow], list[str]]] = {}


def _sku_key(shop_domain: str, pattern: str) -> str:
    return f"{shop_domain}\n{pattern.strip()}"


def get_sku_weight_catalog(
    shop_domain: str, pattern: str
) -> tuple[list[SkuWeightVariantRow], list[str]] | None:
    return _sku_weight_catalog.get(_sku_key(shop_domain, pattern))


def set_sku_weight_catalog(
    shop_domain: str,
    pattern: str,
    rows: list[SkuWeightVariantRow],
    warnings: list[str],
) -> None:
    _sku_weight_catalog[_sku_key(shop_domain, pattern)] = (rows, list(warnings))


def invalidate_sku_weight_catalog(shop_domain: str, pattern: str) -> None:
    _ = _sku_weight_catalog.pop(_sku_key(shop_domain, pattern), None)


_add_variant_catalog: dict[str, tuple[list[AddVariantCatalogRow], list[str]]] = {}


def _av_key(shop_domain: str, pattern: str) -> str:
    return f"{shop_domain}\n{pattern.strip()}"


def get_add_variant_catalog(
    shop_domain: str, pattern: str
) -> tuple[list[AddVariantCatalogRow], list[str]] | None:
    return _add_variant_catalog.get(_av_key(shop_domain, pattern))


def set_add_variant_catalog(
    shop_domain: str,
    pattern: str,
    rows: list[AddVariantCatalogRow],
    warnings: list[str],
) -> None:
    _add_variant_catalog[_av_key(shop_domain, pattern)] = (rows, list(warnings))


def invalidate_add_variant_catalog(shop_domain: str, pattern: str) -> None:
    _ = _add_variant_catalog.pop(_av_key(shop_domain, pattern), None)
