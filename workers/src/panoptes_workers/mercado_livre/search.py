from urllib.parse import quote, urljoin, urlsplit

from panoptes_contracts.discovery import SearchCandidate
from panoptes_contracts.sources import captcha_page
from selectolax.lexbor import LexborHTMLParser

from .identity import canonical_url, key_from_url

HOST = "lista.mercadolivre.com.br"


def pagination(tree):
    node = tree.css_first(".andes-pagination__button--next a, a[rel=next]")
    if node is None:
        return None, False
    for element in (node, node.parent):
        if element and (
            element.attributes.get("aria-disabled") == "true"
            or "--disabled" in element.attributes.get("class", "")
        ):
            return None, False
    href = node.attributes.get("href", "").strip()
    if not href or href.startswith(("#", "?")):
        return None, True
    try:
        url = urljoin(f"https://{HOST}", href)
        parts = urlsplit(url)
        if (
            parts.scheme == "https"
            and parts.hostname == HOST
            and parts.port in (None, 443)
            and not parts.username
            and not parts.password
            and parts.path not in ("", "/")
            and not parts.fragment
        ):
            return url, False
    except ValueError:
        pass
    return None, True


def pagination_unavailable(html):
    return pagination(LexborHTMLParser(html))[1]


def search_url(term, book_only=False):
    return f"https://{HOST}/" + quote("-".join(term.strip().split()), safe="")


def parse_search(html, snapshot_id, page):
    if captcha_page(f"https://{HOST}", html):
        raise ValueError("captcha")
    tree = LexborHTMLParser(html)
    candidates, seen = [], set()
    for position, card in enumerate(
        tree.css(".ui-search-layout__item, .ui-search-result"), 1
    ):
        link = card.css_first("a.poly-component__title, a.ui-search-link")
        if link is None:
            continue
        url = link.attributes.get("href", "")
        try:
            key = key_from_url(url)
            url = canonical_url(url)
        except ValueError:
            continue
        title_node = card.css_first(".poly-component__title, .ui-search-item__title")
        title = (
            title_node.text(separator=" ", strip=True)
            if title_node
            else link.attributes.get("title")
        )
        if not title or key in seen:
            continue
        seen.add(key)
        candidates.append(
            SearchCandidate(
                site="mercado_livre_br",
                source_key=key,
                url=url,
                title=title,
                search_snapshot_id=snapshot_id,
                page_qt=page,
                position_qt=position,
            )
        )
    next_url, _ = pagination(tree)
    if not candidates and not tree.css_first(
        ".ui-search-results, .ui-search-layout, .ui-search-rescue"
    ):
        raise ValueError("search_layout_not_recognized")
    return tuple(candidates), next_url
