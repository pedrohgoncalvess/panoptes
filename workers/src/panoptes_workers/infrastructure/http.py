import asyncio
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx
from panoptes_contracts.sources import SOURCES, captcha_page

PAGE_HOSTS = {host for source in SOURCES.values() for host in source.page_hosts}
IMAGE_HOSTS = {
    "m.media-amazon.com",
    "images-na.ssl-images-amazon.com",
    "images-eu.ssl-images-amazon.com",
    "images-fe.ssl-images-amazon.com",
    "images.amazon.com",
    "ecx.images-amazon.com",
}
IMAGE_HOSTS.update(host for source in SOURCES.values() for host in source.image_hosts)


@dataclass(frozen=True)
class Download:
    source_url: str
    final_url: str
    body: bytes
    status: int
    media_type: str
    encoding: str = "utf-8"
    capture_mode: str = "http"


def validate_url(url: str, *, image: bool = False, allowed_hosts=None):
    parts = urlsplit(url)
    hosts = (
        allowed_hosts
        if allowed_hosts is not None
        else IMAGE_HOSTS
        if image
        else PAGE_HOSTS
    )
    if (
        parts.scheme != "https"
        or parts.hostname not in hosts
        or parts.port not in (None, 443)
        or parts.username
        or parts.password
    ):
        raise ValueError("url_outside_allowed_hosts")


async def download(
    client: httpx.AsyncClient,
    lock: asyncio.Lock,
    url: str,
    interval: float,
    *,
    image: bool = False,
    allowed_hosts=None,
) -> Download:
    source = url
    for _ in range(6):
        validate_url(url, image=image, allowed_hosts=allowed_hosts)
        async with lock:
            await asyncio.sleep(interval)
            async with client.stream("GET", url, follow_redirects=False) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                body = bytearray()
                limit = 10_000_000 if image else 6_000_000
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > limit:
                        raise ValueError("response_too_large")
                media_type = (
                    response.headers.get("content-type", "application/octet-stream")
                    .split(";", 1)[0]
                    .lower()
                )
                if image and (
                    not media_type.startswith("image/") or response.status_code != 200
                ):
                    raise ValueError("invalid_image_response")
                return Download(
                    source,
                    str(response.url),
                    bytes(body),
                    response.status_code,
                    media_type,
                    response.encoding,
                )
    raise ValueError("too_many_redirects")


def block_reason(page: Download) -> str | None:
    if captcha_page(page.final_url, page.body):
        return "captcha"
    body = page.body.lower()
    if any(
        marker in urlsplit(page.final_url).path.lower()
        for marker in (
            "/account-verification",
            "/registration",
            "/login",
            "/auth/",
            "/gz/verification",
        )
    ):
        return "account_verification_required"
    if any(
        marker in body
        for marker in (
            b"validatecaptcha",
            b"captchacharacters",
            b"enter the characters you see below",
            b"sorry, we just need to make sure you're not a robot",
        )
    ):
        return "captcha"
    return {
        401: "authentication_required",
        403: "access_denied",
        429: "rate_limited",
    }.get(page.status)


def is_blocked(page: Download) -> bool:
    return block_reason(page) is not None
