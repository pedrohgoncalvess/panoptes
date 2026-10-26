import re
from urllib.parse import urlsplit

from ..common.matching import normalize as normalize
from ..common.matching import validate_candidate as validate_candidate

HOST = "www.amazon.com.br"
PARSER_VERSION = "1.0.0"


def product_url(asin: str) -> str:
    if not re.fullmatch(r"[A-Z0-9]{10}", asin):
        raise ValueError("invalid_asin")
    return f"https://{HOST}/dp/{asin}"


def asin_from_url(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname != HOST
        or parts.port not in (None, 443)
    ):
        raise ValueError("invalid_product_host")
    match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:/|$)", parts.path)
    if not match:
        raise ValueError("invalid_product_url")
    return match.group(1)
