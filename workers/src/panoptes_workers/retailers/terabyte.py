"""terabyte parser entrypoints."""

from functools import partial

from .product import parse_product
from .search import parse_search as _search
from .search import search_url as _url

parse_catalog_product = partial(parse_product, "terabyte_br")
parse_search = partial(_search, "terabyte_br")
search_url = partial(_url, "terabyte_br")
