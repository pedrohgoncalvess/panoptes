import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from panoptes_contracts.sources import captcha_page
from panoptes_workers.infrastructure.browser import BrowserClient
from panoptes_workers.workflow import runner


@pytest.mark.parametrize("recovers", [True, False])
@pytest.mark.parametrize("failure", ["read", "timeout", "protocol", "503"])
async def test_browser_retries_transient_transport_errors(
    monkeypatch, recovers, failure
):
    browser = BrowserClient("http://test", "token")
    request = httpx.Request("POST", "http://test/internal/browser/fetch")
    error = {
        "read": httpx.ReadError("connection closed", request=request),
        "timeout": httpx.ReadTimeout("timed out", request=request),
        "protocol": httpx.RemoteProtocolError("closed", request=request),
        "503": httpx.HTTPStatusError(
            "unavailable",
            request=request,
            response=httpx.Response(503, request=request),
        ),
    }[failure]
    ok = httpx.Response(200, json={"fallback": True}, request=request)
    browser.client.post = AsyncMock(
        side_effect=[error, ok] if recovers else [error] * 3
    )
    sleep = AsyncMock()
    monkeypatch.setattr("panoptes_workers.infrastructure.browser.asyncio.sleep", sleep)
    try:
        if recovers:
            assert (
                await browser.fetch(
                    "kabum_br", "https://www.kabum.com.br/", asyncio.Lock(), 0
                )
                is None
            )
        else:
            with pytest.raises(type(error)):
                await browser.fetch(
                    "kabum_br", "https://www.kabum.com.br/", asyncio.Lock(), 0
                )
        assert browser.client.post.await_count == (2 if recovers else 3)
        assert [c.args[0] for c in sleep.await_args_list if c.args[0]] == (
            [2] if recovers else [2, 4]
        )
    finally:
        await browser.close()


async def test_browser_never_retries_verification_or_permanent_errors():
    browser = BrowserClient("http://test", "token")
    request = httpx.Request("POST", "http://test/internal/browser/fetch")
    try:
        browser.client.post = AsyncMock(
            return_value=httpx.Response(
                200, json={"blocked": "verification_required"}, request=request
            )
        )
        assert await browser.fetch(
            "amazon_br", "https://www.amazon.com.br/", asyncio.Lock(), 0
        ) == {"blocked": "verification_required"}
        browser.client.post.assert_awaited_once()
        browser.client.post = AsyncMock(
            return_value=httpx.Response(403, request=request)
        )
        with pytest.raises(httpx.HTTPStatusError):
            await browser.fetch(
                "amazon_br", "https://www.amazon.com.br/", asyncio.Lock(), 0
            )
        browser.client.post.assert_awaited_once()
    finally:
        await browser.close()


async def test_unavailable_sites_resume_after_reconnection():
    browser = BrowserClient("http://test", "token")
    request = httpx.Request("GET", "http://test/internal/browser/availability")
    browser.client.get = AsyncMock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "amazon_br": "verification_required",
                    "pichau_br": "connected",
                    "terabyte_br": "disconnected",
                },
                request=request,
            ),
            httpx.Response(200, json={"amazon_br": "connected"}, request=request),
        ]
    )
    try:
        assert await browser.unavailable_sites() == ["amazon_br"]
        assert await browser.unavailable_sites() == []
    finally:
        await browser.close()


@pytest.mark.parametrize("failed", [False, True])
async def test_scheduler_checks_browser_before_opening_transaction(monkeypatch, failed):
    session = Mock()
    opened = Mock()

    @asynccontextmanager
    async def work(_):
        opened()
        yield session

    enqueue = AsyncMock()
    monkeypatch.setattr(runner, "unit_of_work", work)
    monkeypatch.setattr(runner.queue_repository, "enqueue_due", enqueue)
    browser = Mock()
    browser.unavailable_sites = AsyncMock(
        side_effect=httpx.ConnectError("down") if failed else None,
        return_value=["amazon_br"],
    )
    await runner.enqueue_available(None, browser)
    if failed:
        enqueue.assert_not_awaited()
        opened.assert_not_called()
    else:
        enqueue.assert_awaited_once_with(session, ["amazon_br"])


def test_mercado_livre_micro_landing_is_a_challenge_without_changing_normal_pages():
    html = """<title>Rx 9060 Xt | Mercado Livre</title>
    <button id="continue-button" class="micro-landing-button">Continuar</button>
    <noscript>This page requires JavaScript to work.</noscript>"""
    assert captcha_page("https://lista.mercadolivre.com.br/RX-9060-XT", html)
    assert not captcha_page("https://www.amazon.com.br/", html)
    assert not captcha_page(
        "https://lista.mercadolivre.com.br/RX-9060-XT",
        '<button id="continue-button">Continuar</button>',
    )
