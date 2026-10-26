"""kabum parser entrypoints."""

from functools import partial

from .product import parse_product
from .search import parse_search as _search
from .search import search_url as _url

parse_catalog_product = partial(parse_product, "kabum_br")
parse_search = partial(_search, "kabum_br")
search_url = partial(_url, "kabum_br")
