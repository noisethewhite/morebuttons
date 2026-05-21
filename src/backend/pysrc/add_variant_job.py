from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from .catalog_cache import set_add_variant_catalog
from .fileloader import FileLoader
from .graphql import GraphQL
from .graphqldc.products import (
    AddVariantCatalogRow,
    AddVariantCatalogStepDone,
    AddVariantCatalogStepPending,
    AddVariantCatalogStepResult,
    ProductsAddVariantQueryData,
)


@dataclass
class AddVariantCatalogJob:
    id: str
    shop_domain: str
    token: str
    pattern: str
    rows: list[AddVariantCatalogRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    after: str | None = None
    exhausted: bool = False
    completed_steps: int = 0
    _compiled: re.Pattern | None = field(init=False)
    _query: str = field(init=False)

    def __post_init__(self) -> None:
        self._query = FileLoader.load("products_add_variant_page.gql")
        try:
            self._compiled = re.compile(self.pattern, re.IGNORECASE)
        except re.error as e:
            self._compiled = None
            self.warnings.append(f"Invalid regex pattern: {e}")
            self.exhausted = True

    def step(self) -> AddVariantCatalogStepResult:
        self.completed_steps += 1
        if self.exhausted:
            return self._finish()
        return self._step_products()

    def _step_products(self) -> AddVariantCatalogStepResult:
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
                expected_type=ProductsAddVariantQueryData,
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
            first_option_name = prod.options[0].name if prod.options else "Title"

            if not prod.variants:
                continue
            if prod.variants.pageInfo.hasNextPage is True:
                self.warnings.append(
                    f'Product "{ptitle}" has more than 100 variants; '
                    "only the first page was loaded."
                )

            all_skus: list[str] = []
            matching_skus: list[str] = []
            for ve in prod.variants.edges:
                sku = (ve.node.sku or "").strip()
                if sku:
                    all_skus.append(sku)
                    if compiled.search(sku):
                        matching_skus.append(sku)

            if not matching_skus:
                continue

            base_prefix = matching_skus[0].rsplit("-", 1)[0]
            self.rows.append(AddVariantCatalogRow(
                productId=pid,
                productTitle=ptitle,
                firstOptionName=first_option_name,
                baseSkuPrefix=base_prefix,
                allVariantSkus=all_skus,
            ))

        nxt = parsed.products.pageInfo.next_page_cursor()
        if nxt is None:
            self.exhausted = True
        else:
            self.after = nxt

        if self.exhausted:
            return self._finish()
        return AddVariantCatalogStepPending(
            completed=self.completed_steps,
            remaining=1,
            total=self.completed_steps + 1,
        )

    def _finish(self) -> AddVariantCatalogStepDone:
        set_add_variant_catalog(self.shop_domain, self.pattern, self.rows, self.warnings)
        return AddVariantCatalogStepDone(
            completed=self.completed_steps,
            total=self.completed_steps,
            pattern=self.pattern,
            productCount=len(self.rows),
            warnings=list(self.warnings),
        )


_JOBS: dict[str, AddVariantCatalogJob] = {}


def create_add_variant_catalog_job(shop_domain: str, token: str, pattern: str) -> str:
    jid = uuid.uuid4().hex
    _JOBS[jid] = AddVariantCatalogJob(
        id=jid, shop_domain=shop_domain, token=token, pattern=pattern
    )
    return jid


def take_add_variant_catalog_job(job_id: str) -> AddVariantCatalogJob | None:
    return _JOBS.get(job_id)


def delete_add_variant_catalog_job(job_id: str) -> None:
    _ = _JOBS.pop(job_id, None)
