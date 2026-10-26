import re
from urllib.parse import urlsplit, urlunsplit

from panoptes_contracts.sources import SOURCES


def key_from_url(url):
    parts = urlsplit(str(url))
    if (
        parts.scheme != "https"
        or parts.hostname not in SOURCES["mercado_livre_br"].page_hosts
        or parts.port not in (None, 443)
        or parts.username
        or parts.password
    ):
        raise ValueError("invalid_product_host")
    match = re.search(r"(?:/p/|/)(MLB-?\d{6,14})(?:[/?_-]|$)", parts.path)
    if not match:
        raise ValueError("invalid_product_url")
    return match.group(1).replace("-", "")


def canonical_url(url):
    key_from_url(url)
    parts = urlsplit(str(url))
    return urlunsplit(("https", parts.hostname, parts.path, "", ""))
