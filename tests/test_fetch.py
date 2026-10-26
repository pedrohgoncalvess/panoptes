import asyncio

import httpx
import pytest
from panoptes_workers.infrastructure.http import (
    Download,
    block_reason,
    download,
    is_blocked,
)


async def test_redirect_to_external_host_is_rejected_before_request():
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(
            302, headers={"location": "https://evil.example/dp/1492040347"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError, match="allowed_hosts"):
            await download(
                client, asyncio.Lock(), "https://www.amazon.com.br/dp/1492040347", 0
            )
    assert len(calls) == 1


async def test_captcha_is_recognized_even_on_success_status():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                content=b'<form action="/errors/validateCaptcha">Captcha</form>',
                headers={"content-type": "text/html"},
            )
        )
    ) as client:
        page = await download(
            client, asyncio.Lock(), "https://www.amazon.com.br/s?k=test", 0
        )
        assert is_blocked(page)


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (503, b"Algo deu errado", None),
        (503, b'<form action="validateCaptcha">', "captcha"),
        (403, b"Forbidden", "access_denied"),
        (429, b"Too many requests", "rate_limited"),
    ],
)
def test_block_reason_distinguishes_unavailable_from_access_restrictions(
    status, body, reason
):
    page = Download(
        "https://www.amazon.com.br/s?k=test",
        "https://www.amazon.com.br/s?k=test",
        body,
        status,
        "text/html",
    )
    assert block_reason(page) == reason
    assert is_blocked(page) == (reason is not None)
