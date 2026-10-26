"""One adapter per source; workflow, matching and persistence remain shared."""

import re
from dataclasses import dataclass
from functools import partial

from panoptes_contracts.sources import SOURCES, SourceDefinition

from .amazon import product as amazon_product
from .amazon import search as amazon_search
from .common.hardware import validate_hardware
from .common.matching import validate_candidate
from .mercado_livre import product as ml_product
from .mercado_livre import search as ml_search
from .retailers import product as retail_product
from .retailers import search as retail_search
from .retailers.identity import RETAILERS


@dataclass(frozen=True)
class SourceAdapter:
    definition: SourceDefinition
    search_url: object
    parse_search: object
    parse_product: object
    title_locator: str
    parser_version: str = "1.0.0"
    pagination_unavailable: object = None

    def validate(self, candidate, criteria, **kwargs):
        hardware = validate_hardware(candidate, criteria)
        if hardware is not None:
            return hardware
        original = candidate
        if (
            self.definition.id == "mercado_livre_br"
            and criteria.match_mode == "exact_product"
        ):
            title = re.sub(r"^livro\s*(?:[-:]\s*)?", "", candidate.title, flags=re.I)
            candidate = candidate.model_copy(update={"title": title})
        result = validate_candidate(candidate, criteria, **kwargs)
        return result.model_copy(
            update={
                "candidate": original,
                "validator_version": f"{self.definition.id}_product_match/1.0.0",
            }
        )


ADAPTERS = {
    "amazon_br": SourceAdapter(
        SOURCES["amazon_br"],
        amazon_search.search_url,
        amazon_search.parse_search,
        amazon_product.parse_catalog_product,
        "#productTitle",
        parser_version="1.0.1",
    ),
    "mercado_livre_br": SourceAdapter(
        SOURCES["mercado_livre_br"],
        ml_search.search_url,
        ml_search.parse_search,
        ml_product.parse_catalog_product,
        'h1.ui-pdp-title,h1[itemprop=name],script[type="application/ld+json"]',
        parser_version="1.0.1",
        pagination_unavailable=ml_search.pagination_unavailable,
    ),
}

for site in RETAILERS:
    ADAPTERS[site] = SourceAdapter(
        SOURCES[site],
        partial(retail_search.search_url, site),
        partial(retail_search.parse_search, site),
        partial(retail_product.parse_product, site),
        "h1",
    )


def get_source(site="amazon_br"):
    try:
        return ADAPTERS[site]
    except KeyError:
        raise ValueError("unsupported_source") from None


def source_for_url(url):
    from urllib.parse import urlsplit

    host = urlsplit(str(url)).hostname
    for adapter in ADAPTERS.values():
        if host in adapter.definition.page_hosts:
            return adapter
    raise ValueError("url_outside_allowed_hosts")
