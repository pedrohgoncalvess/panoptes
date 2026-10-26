from urllib.parse import quote, urlencode, urljoin

from panoptes_contracts.discovery import SearchCandidate
from panoptes_contracts.sources import captcha_page
from selectolax.lexbor import LexborHTMLParser

from .identity import canonical_url, key_from_url
from .product import next_data

CONFIG = {
    "kabum_br": (
        "https://www.kabum.com.br",
        "a.productLink, a[href*='/produto/']",
        "h2,h3,.nameCard",
    ),
    "pichau_br": (
        "https://www.pichau.com.br",
        'a[data-cy="list-product"],.product-item a[href]',
        "h2,h3,.product-item-name",
    ),
    "terabyte_br": (
        "https://www.terabyteshop.com.br",
        ".pbox a[href],.product-item a[href]",
        "h2,h3,.prod-name",
    ),
}


def search_url(site, term, book_only=False):
    base = CONFIG[site][0]
    if site == "kabum_br":
        return base + "/busca/" + quote("-".join(term.strip().split()), safe="")
    return (
        base
        + ("/search?" if site == "pichau_br" else "/busca?")
        + urlencode({"q" if site == "pichau_br" else "str": term})
    )


def parse_search(site, html, snapshot_id, page):
    base, selector, title_selector = CONFIG[site]
    if captcha_page(base, html):
        raise ValueError("captcha")
    tree = LexborHTMLParser(html)
    scope = tree.css_first("#main-content") or tree
    candidates, seen = [], set()

    def add(url, title):
        try:
            key = key_from_url(site, url)
            url = canonical_url(site, url)
        except ValueError:
            return
        if not title or key in seen:
            return
        seen.add(key)
        candidates.append(
            SearchCandidate(
                site=site,
                source_key=key,
                url=url,
                title=title,
                search_snapshot_id=snapshot_id,
                page_qt=page,
                position_qt=len(candidates) + 1,
            )
        )

    catalog = (
        next_data(tree).get("data", {}).get("catalogServer", {})
        if site == "kabum_br"
        else {}
    )
    for product in catalog.get("data", []):
        if isinstance(product, dict) and product.get("code"):
            add(
                f"{base}/produto/{product['code']}/{product.get('friendlyName', '')}",
                product.get("name"),
            )
    for link in scope.css(selector):
        url = urljoin(base, link.attributes.get("href", ""))
        heading = link.css_first(title_selector)
        # Pichau puts the title inside the product link. Do not treat navigation as products.
        title = (
            heading.text(separator=" ", strip=True)
            if heading
            else link.attributes.get("title")
        )
        add(url, title)
    next_node = tree.css_first('a[rel="next"],a[aria-label="Go to next page"]')
    next_url = None
    pagination = catalog.get("pagination", {})
    if isinstance(pagination.get("next"), int) and pagination["next"] > page:
        term = next_data(tree).get("data", {}).get("searchTermWithoutHyphen")
        if term:
            next_url = (
                search_url(site, term)
                + "?"
                + urlencode({"page_number": pagination["next"]})
            )
    if next_node and next_node.attributes.get("href"):
        from panoptes_contracts.sources import SOURCES

        from ..infrastructure.http import validate_url

        next_url = urljoin(base, next_node.attributes["href"])
        validate_url(next_url, allowed_hosts=SOURCES[site].page_hosts)
    if not candidates:
        text = tree.text(separator=" ", strip=True).lower()
        if catalog.get("meta", {}).get("totalItemsCount") != 0 and not any(
            marker in text
            for marker in (
                "nenhum produto encontrado",
                "nenhum resultado encontrado",
                "não encontramos produtos",
                "nao encontramos produtos",
            )
        ):
            raise ValueError("search_layout_not_recognized")
    return tuple(candidates), next_url
