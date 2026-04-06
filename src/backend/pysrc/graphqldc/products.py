from __future__ import annotations

from dataclasses import field
from decimal import Decimal
from typing import Literal

from pydantic import ConfigDict
from pydantic.dataclasses import dataclass

from ..symbols import Currency
from ..utils import Utils
from .common import Connection, Jsonable
from .shipping import PreviewRateRow, UserError

_CONFIG = ConfigDict(extra="ignore")


# --- product_tags_page.gql ---


@dataclass(config=_CONFIG)
class ProductTagLabel:
    """When ``productTags`` returns object nodes (e.g. ``name``) instead of plain strings."""

    name: str | None = None


@dataclass(config=_CONFIG)
class ProductTagsQueryData:
    productTags: Connection[str | ProductTagLabel]

    def iter_tag_strings(self) -> list[str]:
        """Flatten tag nodes to non-empty strings."""
        out: list[str] = []
        for e in self.productTags.edges:
            out.append(_tag_node_to_str(e.node))
        return [s for s in out if s]


def _tag_node_to_str(node: str | ProductTagLabel) -> str:
    match node:
        case str(s):
            return s
        case ProductTagLabel(name=n) if n:
            return n
        case ProductTagLabel():
            return ""


# --- products_by_tag_page.gql ---


@dataclass(config=_CONFIG)
class TaggedVariantRow:
    """Aggregated variant row for tag pricing (app-level, not a single GQL type)."""

    productId: str
    productTitle: str
    variantId: str
    variantTitle: str
    amount: str
    currencyCode: str

    def new_price_amount(
        self,
        adjustment_mode: Literal["percent", "offset"],
        percent: float,
    ) -> str:
        if adjustment_mode == "percent":
            factor = Decimal(1) + Decimal(str(percent)) / Decimal(100)
            return Utils.scale_money(self.amount, factor)
        delta = Decimal(str(percent))
        return Utils.offset_money(self.amount, delta)

    def preview_rate_row(
        self,
        adjustment_mode: Literal["percent", "offset"],
        percent: float,
    ) -> PreviewRateRow:
        new_amt = self.new_price_amount(adjustment_mode, percent)
        boundary = self.variantTitle.strip() or "Default"
        return PreviewRateRow(
            id=self.variantId,
            boundary=boundary,
            current=Currency.format_amount(self.amount, self.currencyCode),
            new=Currency.format_amount(new_amt, self.currencyCode),
        )


@dataclass(config=_CONFIG)
class ProductVariantNode:
    id: str
    title: str | None = None
    """``price`` is the Admin API ``Money`` scalar (decimal string, shop currency)."""
    price: str | None = None

    def to_tagged_variant_row(
        self,
        product_id: str,
        product_title: str,
        shop_currency_code: str,
    ) -> TaggedVariantRow | None:
        p = self.price
        if p is None or not str(p).strip():
            return None
        return TaggedVariantRow(
            productId=product_id,
            productTitle=product_title,
            variantId=self.id,
            variantTitle=(self.title or "").strip(),
            amount=str(p).strip(),
            currencyCode=shop_currency_code.upper(),
        )


@dataclass(config=_CONFIG)
class ProductListNode:
    id: str
    title: str | None = None
    variants: Connection[ProductVariantNode] | None = None

    def collect_tagged_variant_rows(
        self,
        shop_currency_code: str,
    ) -> tuple[list[TaggedVariantRow], list[str]]:
        warnings: list[str] = []
        rows: list[TaggedVariantRow] = []
        v = self.variants
        if v is None:
            return rows, warnings
        if v.pageInfo.hasNextPage is True:
            warnings.append(
                f"Product {self.id} has more than 100 variants; " + \
                "only the first page was loaded."
            )
        ptitle = self.title or ""
        for ve in v.edges:
            r = ve.node.to_tagged_variant_row(self.id, ptitle, shop_currency_code)
            if r is not None:
                rows.append(r)
        return rows, warnings


@dataclass(config=_CONFIG)
class ShopCurrencyRoot:
    currencyCode: str


@dataclass(config=_CONFIG)
class ProductsByTagQueryData:
    shop: ShopCurrencyRoot
    products: Connection[ProductListNode]


# --- product_variants_bulk_update.gql (replaces deprecated productVariantUpdate in API 2024-10+) ---


@dataclass(config=_CONFIG)
class ProductVariantsBulkInputRow:
    """``price`` is the Admin API ``Money`` scalar (amount string, shop currency)."""

    id: str
    price: str


@dataclass(config=_CONFIG)
class ProductVariantsBulkUpdateVariables(Jsonable):
    productId: str
    variants: list[ProductVariantsBulkInputRow]


@dataclass(config=_CONFIG)
class ProductVariantSnippet:
    """``price`` is the ``Money`` scalar string on ``ProductVariant``."""

    id: str | None = None
    price: str | None = None


@dataclass(config=_CONFIG)
class ProductVariantsBulkUpdatePayload:
    productVariants: list[ProductVariantSnippet] | None = None
    userErrors: list[UserError] | None = None

    def user_error_messages(self) -> list[str]:
        out: list[str] = []
        for ue in self.userErrors or []:
            m = ue.message
            if m:
                out.append(m)
        return out

    def mutation_succeeded(self) -> bool:
        return not self.userErrors


@dataclass(config=_CONFIG)
class ProductVariantsBulkUpdateData:
    productVariantsBulkUpdate: ProductVariantsBulkUpdatePayload | None = None


# --- product tag catalog job (HTTP step responses) ---


@dataclass(config=_CONFIG)
class ProductTagCatalogStepPending(Jsonable):
    """In-progress stepped load; more Shopify GraphQL steps may follow."""

    completed: int
    remaining: int
    total: int
    done: Literal[False] = False
    phase: Literal["product_tag"] = "product_tag"


@dataclass(config=_CONFIG)
class ProductTagCatalogStepDone(Jsonable):
    """Catalog load finished; tagged variant cache is populated."""

    completed: int
    total: int
    tag: str
    variantCount: int
    warnings: list[str] = field(default_factory=list)
    done: Literal[True] = True
    remaining: int = 0
    phase: Literal["product_tag"] = "product_tag"


ProductTagCatalogStepResult = ProductTagCatalogStepPending | ProductTagCatalogStepDone
