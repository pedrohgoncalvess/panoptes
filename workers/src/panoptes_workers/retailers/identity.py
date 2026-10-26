import re
from urllib.parse import urlsplit, urlunsplit

from panoptes_contracts.sources import SOURCES

RETAILERS = ("kabum_br", "pichau_br", "terabyte_br")


def key_from_url(site, url):
    parts = urlsplit(str(url))
    if (
        parts.scheme != "https"
        or parts.hostname not in SOURCES[site].page_hosts
        or parts.port not in (None, 443)
        or parts.username
        or parts.password
    ):
        raise ValueError("invalid_product_host")
    if site == "pichau_br":
        # Magento product URLs are slugs; categories/search have multiple segments.
        match = re.fullmatch(r"/([a-z0-9]+(?:-[a-z0-9]+)+)/?", parts.path)
    else:
        match = re.fullmatch(r"/produto/(\d{1,12})(?:/[^/]+)?/?", parts.path)
    if not match:
        raise ValueError("invalid_product_url")
    return match[1]


def canonical_url(site, url):
    key_from_url(site, url)
    parts = urlsplit(str(url))
    return urlunsplit(
        ("https", SOURCES[site].page_hosts[0], parts.path.rstrip("/"), "", "")
    )
