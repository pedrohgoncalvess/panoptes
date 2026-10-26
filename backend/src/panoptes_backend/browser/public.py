"""Anonymous rendered capture for public retailers; no saved login required."""

from urllib.parse import urlsplit

from panoptes_contracts.sources import SOURCES, captcha_page


async def wait_for_public_page(page):
    from playwright.async_api import TimeoutError as BrowserTimeout

    try:
        await page.wait_for_function(
            """() => {
            const text = document.body?.innerText || '';
            if (/ATUALIZANDO INFORMA/i.test(text)) return false;
            return !!document.querySelector('h1,a[href*="/produto/"],a h2,a h3')
                || /nenhum (produto|resultado) encontrado/i.test(text);
        }""",
            timeout=12000,
        )
    except BrowserTimeout:
        pass


async def capture_public(browser, site, url):
    definition = SOURCES[site]
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname not in definition.page_hosts
        or parts.port not in (None, 443)
        or parts.username
        or parts.password
    ):
        raise ValueError("url_outside_allowed_hosts")
    context = await browser.new_context(locale="pt-BR")
    try:

        async def route(request):
            parts = urlsplit(request.request.url)
            host = parts.hostname or ""
            domains = tuple(h.removeprefix("www.") for h in definition.page_hosts)
            allowed = (
                parts.scheme == "https"
                and parts.port in (None, 443)
                and not parts.username
                and not parts.password
                and (
                    host in definition.image_hosts
                    or any(host == d or host.endswith("." + d) for d in domains)
                )
            )
            # Top-level redirects must remain inside the page host allowlist.
            if (
                request.request.is_navigation_request()
                and request.request.frame == page.main_frame
            ):
                allowed = allowed and host in definition.page_hosts
            await request.continue_() if allowed else await request.abort()

        page = await context.new_page()
        await context.route("**/*", route)
        response = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        status = response.status if response else 503
        body = await page.content()
        if status == 200 and not captcha_page(page.url, body):
            await wait_for_public_page(page)
            body = await page.content()
        if len(body.encode()) > 6_000_000:
            raise ValueError("response_too_large")
        if urlsplit(page.url).hostname not in definition.page_hosts:
            raise ValueError("url_outside_allowed_hosts")
        return {
            "body": body,
            "status": status,
            "final_url": page.url,
            "media_type": response.headers.get("content-type", "text/html")
            .split(";", 1)[0]
            .lower()
            if response
            else "text/html",
            "capture_mode": "browser",
        }
    finally:
        await context.close()
