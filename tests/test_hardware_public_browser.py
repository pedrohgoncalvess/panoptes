import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from panoptes_backend.browser.public import capture_public
from panoptes_backend.browser.service import BrowserConnections


def browser_mock(status=200):
    response = SimpleNamespace(
        status=status, headers={"content-type": "text/html; charset=utf-8"}
    )
    page = SimpleNamespace(
        goto=AsyncMock(return_value=response),
        content=AsyncMock(return_value="<h1>SSD Kingston</h1>"),
        wait_for_function=AsyncMock(),
        main_frame=object(),
        url="https://www.pichau.com.br/ssd-kingston",
    )
    context = SimpleNamespace(
        new_page=AsyncMock(return_value=page), route=AsyncMock(), close=AsyncMock()
    )
    return SimpleNamespace(new_context=AsyncMock(return_value=context)), context, page


async def test_kabum_public_capture_does_not_require_authenticated_session():
    browser, context, page = browser_mock()
    page.url = "https://www.kabum.com.br/produto/123/ssd-kingston"
    service = BrowserConnections.__new__(BrowserConnections)
    service.locks = {"kabum_br": asyncio.Lock()}
    service.live = {}
    service.ensure_browser = AsyncMock(return_value=browser)
    service.read = Mock(return_value={"status": "disconnected"})
    result = await service.fetch("kabum_br", page.url)
    assert result["capture_mode"] == "browser"
    assert result["status"] == 200
    assert result["body"] == "<h1>SSD Kingston</h1>"
    context.close.assert_awaited_once()


async def test_public_context_is_closed_when_navigation_fails():
    browser, context, page = browser_mock()
    page.goto.side_effect = RuntimeError("network failed")
    with pytest.raises(RuntimeError, match="network failed"):
        await capture_public(browser, "pichau_br", page.url)
    context.close.assert_awaited_once()


async def test_public_browser_does_not_retry_or_interact_with_challenges():
    browser, context, page = browser_mock(403)
    page.content.return_value = "<title>Just a moment...</title>"
    result = await capture_public(browser, "pichau_br", page.url)
    assert result["status"] == 403
    page.wait_for_function.assert_not_awaited()
    page.goto.assert_awaited_once()


async def test_public_browser_blocks_cross_store_documents():
    browser, context, page = browser_mock()
    await capture_public(browser, "pichau_br", page.url)
    callback = context.route.await_args.args[1]
    route = SimpleNamespace(
        request=SimpleNamespace(
            url="https://evil.example/",
            frame=page.main_frame,
            is_navigation_request=lambda: True,
        ),
        continue_=AsyncMock(),
        abort=AsyncMock(),
    )
    await callback(route)
    route.abort.assert_awaited_once()
    route.continue_.assert_not_awaited()
    with pytest.raises(ValueError, match="url_outside_allowed_hosts"):
        await capture_public(browser, "pichau_br", "https://127.0.0.1/")
