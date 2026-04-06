from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from .catalog_cache import (
    get_tagged_variants_catalog,
    invalidate_tagged_variants_catalog,
    set_tagged_variants_catalog,
)
from .fileloader import FileLoader
from .graphql import GraphQL
from .graphqldc.products import (
    ProductTagCatalogStepDone,
    ProductTagCatalogStepPending,
    ProductTagCatalogStepResult,
    ProductTagsQueryData,
    ProductVariantsBulkInputRow,
    ProductVariantsBulkUpdateData,
    ProductVariantsBulkUpdateVariables,
    ProductsByTagQueryData,
    TaggedVariantRow,
)
from .graphqldc.shipping import PreviewProfileBlock, PreviewZoneBlock


def _tag_search_query(tag: str) -> str:
    t = tag.strip()
    if not t:
        return ""
    if any(c in t for c in "\n\r"):
        t = t.replace("\n", " ").replace("\r", " ")
    if any(c in t for c in ' "\\'):
        escaped = t.replace("\\", "\\\\").replace('"', '\\"')
        return f'tag:"{escaped}"'
    return f"tag:{t}"


def fetch_product_tag_strings(shop_domain: str, access_token: str) -> list[str]:
    q = FileLoader.load("product_tags_page.gql")
    out: list[str] = []
    after: str | None = None
    while True:
        try:
            parsed = GraphQL.send(
                shop_domain,
                access_token,
                q,
                {"first": 100, "after": after},
                expected_type=ProductTagsQueryData,
            )
        except RuntimeError:
            break
        if parsed is None:
            break
        out.extend(parsed.iter_tag_strings())
        nxt = parsed.productTags.pageInfo.next_page_cursor()
        if nxt is None:
            break
        after = nxt
    return sorted(set(out), key=lambda s: (s.lower(), s))


@dataclass
class TaggedProductCatalogJob:
    id: str
    shop_domain: str
    token: str
    tag: str
    rows: list[TaggedVariantRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    after_products: str | None = None
    exhausted: bool = False
    completed_steps: int = 0

    _q_products: str = field(init=False)

    def __post_init__(self) -> None:
        self._q_products = FileLoader.load("products_by_tag_page.gql")

    def _estimate_remaining(self) -> int:
        return 0 if self.exhausted else 1

    def step(self) -> ProductTagCatalogStepResult:
        self.completed_steps += 1
        if self.exhausted:
            return self._finish()
        return self._step_products()

    def _step_products(self) -> ProductTagCatalogStepResult:
        query = _tag_search_query(self.tag)
        if not query:
            self.warnings.append("Empty product tag.")
            self.exhausted = True
            return self._finish()

        try:
            parsed = GraphQL.send(
                self.shop_domain,
                self.token,
                self._q_products,
                {
                    "first": 50,
                    "after": self.after_products,
                    "query": query,
                },
                expected_type=ProductsByTagQueryData,
            )
        except RuntimeError as e:
            self.warnings.append(str(e))
            self.exhausted = True
            return self._finish()

        if parsed is None:
            self.warnings.append("Unexpected response from products query.")
            self.exhausted = True
            return self._finish()

        shop_cc = parsed.shop.currencyCode
        for edge in parsed.products.edges:
            batch, w = edge.node.collect_tagged_variant_rows(shop_cc)
            self.rows.extend(batch)
            self.warnings.extend(w)

        nxt = parsed.products.pageInfo.next_page_cursor()
        if nxt is None:
            self.exhausted = True
        else:
            self.after_products = nxt

        rem = self._estimate_remaining()
        total = self.completed_steps + rem
        if self.exhausted:
            return self._finish()
        return ProductTagCatalogStepPending(
            completed=self.completed_steps,
            remaining=rem,
            total=total,
        )

    def _finish(self) -> ProductTagCatalogStepDone:
        set_tagged_variants_catalog(self.shop_domain, self.tag, self.rows, self.warnings)
        return ProductTagCatalogStepDone(
            completed=self.completed_steps,
            total=self.completed_steps,
            tag=self.tag,
            variantCount=len(self.rows),
            warnings=list(self.warnings),
        )


_TAG_JOBS: dict[str, TaggedProductCatalogJob] = {}


def create_tagged_product_job(shop_domain: str, token: str, tag: str) -> str:
    jid = uuid.uuid4().hex
    _TAG_JOBS[jid] = TaggedProductCatalogJob(
        id=jid, shop_domain=shop_domain, token=token, tag=tag
    )
    return jid


def take_tagged_product_job(job_id: str) -> TaggedProductCatalogJob | None:
    return _TAG_JOBS.get(job_id)


def delete_tagged_product_job(job_id: str) -> None:
    _ = _TAG_JOBS.pop(job_id, None)


def preview_variant_price_changes(
    shop_domain: str,
    tag: str,
    percent: float,
    adjustment_mode: Literal["percent", "offset"] = "percent",
) -> tuple[list[PreviewProfileBlock], list[str]]:
    cached = get_tagged_variants_catalog(shop_domain, tag)
    if cached is None:
        raise RuntimeError(
            "Product catalog for this tag is not loaded. Wait for loading to finish."
        )
    rows, warnings = cached

    by_product: dict[str, tuple[str, list[TaggedVariantRow]]] = {}
    for r in rows:
        if r.productId not in by_product:
            by_product[r.productId] = (r.productTitle, [])
        by_product[r.productId][1].append(r)

    out: list[PreviewProfileBlock] = []
    w = list(warnings)

    for pid in sorted(by_product.keys(), key=lambda i: (by_product[i][0].lower(), i)):
        ptitle, variants = by_product[pid]
        preview_rows = [
            r.preview_rate_row(adjustment_mode, percent)
            for r in sorted(
                variants, key=lambda x: (x.variantTitle.lower(), x.variantId)
            )
        ]
        zone = PreviewZoneBlock(
            id=f"{pid}-variants",
            name="Variants",
            rows=preview_rows,
        )
        out.append(
            PreviewProfileBlock(id=pid, name=ptitle or "Untitled product", zones=[zone])
        )

    return out, w


def apply_variant_price_changes(
    shop_domain: str,
    access_token: str,
    tag: str,
    percent: float,
    adjustment_mode: Literal["percent", "offset"] = "percent",
) -> tuple[int, list[str], list[str]]:
    cached = get_tagged_variants_catalog(shop_domain, tag)
    if cached is None:
        raise RuntimeError("Product catalog for this tag is not loaded.")
    rows, warnings = cached

    mut = FileLoader.load("product_variants_bulk_update.gql")
    user_msgs: list[str] = []
    updated = 0

    by_product: dict[str, list[TaggedVariantRow]] = defaultdict(list)
    for r in rows:
        by_product[r.productId].append(r)

    for product_id, prod_rows in by_product.items():
        variants = [
            ProductVariantsBulkInputRow(
                id=r.variantId,
                price=r.new_price_amount(adjustment_mode, percent),
            )
            for r in prod_rows
        ]
        variables = ProductVariantsBulkUpdateVariables(
            productId=product_id,
            variants=variants,
        )
        parsed, soft_errs = GraphQL.send(
            shop_domain,
            access_token,
            mut,
            variables.to_json(),
            expected_type=ProductVariantsBulkUpdateData,
            raise_on_graphql_error=False,
        )
        if parsed is None:
            user_msgs.extend(soft_errs)
            continue
        payload = parsed.productVariantsBulkUpdate
        if payload is None:
            user_msgs.append(f"Product {product_id}: missing productVariantsBulkUpdate.")
            continue
        if not payload.mutation_succeeded():
            user_msgs.extend(payload.user_error_messages())
        else:
            updated += len(prod_rows)

    invalidate_tagged_variants_catalog(shop_domain, tag)
    return updated, warnings, user_msgs
