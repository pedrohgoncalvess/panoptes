import re
from urllib.parse import urlencode, urljoin, urlsplit
from uuid import UUID

from panoptes_contracts.discovery import SearchCandidate
from panoptes_contracts.sources import captcha_page
from selectolax.lexbor import LexborHTMLParser

from .identity import HOST, product_url


def search_url(term: str, book_only=True) -> str:
    parameters = {"k": term}
    if book_only:
        parameters["i"] = "stripbooks"
    return f"https://{HOST}/s?" + urlencode(parameters)


def parse_search(
    html: bytes, snapshot_id: UUID, page: int
) -> tuple[tuple[SearchCandidate, ...], str | None]:
    if captcha_page(f"https://{HOST}", html):
        raise ValueError("captcha")
    tree = LexborHTMLParser(html)
    candidates = []
    seen = set()
    for position, card in enumerate(
        tree.css('[data-component-type="s-search-result"][data-asin]'), 1
    ):
        asin = card.attributes.get("data-asin", "")
        heading = card.css_first("h2")
        if not re.fullmatch(r"[A-Z0-9]{10}", asin) or asin in seen or heading is None:
            continue
        title = heading.text(separator=" ", strip=True)
        if not title:
            continue
        authors = tuple(node.text(strip=True) for node in card.css("[data-author]"))
        candidates.append(
            SearchCandidate(
                source_key=asin,
                url=product_url(asin),
                title=title,
                authors=authors,
                search_snapshot_id=snapshot_id,
                page_qt=page,
                position_qt=position,
            )
        )
        seen.add(asin)
    next_page = tree.css_first("a.s-pagination-next")
    url = (
        urljoin(f"https://{HOST}", next_page.attributes.get("href", ""))
        if next_page
        else None
    )
    if url and (urlsplit(url).hostname != HOST or urlsplit(url).path != "/s"):
        url = None
    if not candidates and not tree.css_first(
        '[data-component-type="s-search-results"], .s-no-results, #s-search-results'
    ):
        raise ValueError("search_layout_not_recognized")
    return tuple(candidates), url
