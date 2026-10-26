import asyncio
import os
import time
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from panoptes_backend.auth.router import current_user
from panoptes_backend.browser.service import LOGIN, BrowserConnections, permitted
from panoptes_backend.main import create_app
from panoptes_workers.infrastructure.browser import BrowserClient


@pytest.fixture
def connections(tmp_path):
    return BrowserConnections(tmp_path, Fernet.generate_key().decode())


def live(
    connections, *, interactive=False, url="https://www.amazon.com.br/dp/B012345678"
):
    context = AsyncMock()
    context.cookies.return_value = [{"name": "at-acbbr", "value": "secret-cookie"}]
    context.storage_state.return_value = {"cookies": [], "origins": []}
    page = AsyncMock()
    page.is_closed = Mock(return_value=False)
    page.url = url
    page.content.return_value = "<html>Produto</html>"
    page.evaluate.return_value = True
    page.goto.return_value = Mock(
        status=200, headers={"content-type": "text/html; charset=utf-8"}
    )
    entry = {
        "context": context,
        "page": page,
        "interactive": interactive,
        "deadline": time.monotonic() + 900,
    }
    connections.live["amazon_br"] = entry
    return entry


async def test_encrypted_state_restart_and_disconnect(connections):
    entry = live(connections, interactive=True)
    entry["context"].storage_state.return_value = {
        "cookies": [{"value": "secret-cookie"}],
        "origins": [],
    }
    assert (await connections.save("amazon_br"))["status"] == "connected"
    assert b"secret-cookie" not in connections.path("amazon_br").read_bytes()
    restart = BrowserConnections(
        connections.directory,
        Fernet.generate_key().decode(),
    )
    with pytest.raises(HTTPException) as error:
        restart.read("amazon_br")
    assert error.value.status_code == 503
    restart.cipher = connections.cipher
    assert (await restart.status("amazon_br"))["status"] == "connected"
    await connections.disconnect("amazon_br")
    entry["context"].close.assert_awaited_once()
    assert not connections.path("amazon_br").exists()


async def test_login_is_not_saved_without_auth_cookie(connections):
    entry = live(connections, interactive=True)
    entry["context"].cookies.return_value = []
    with pytest.raises(HTTPException) as error:
        await connections.save("amazon_br")
    assert error.value.status_code == 409
    assert not connections.path("amazon_br").exists()


async def test_anonymous_amazon_session_token_is_not_login(connections):
    entry = live(connections, interactive=True)
    entry["context"].cookies.return_value = [
        {"name": "session-token", "value": "anonymous"}
    ]
    assert not await connections.authenticated("amazon_br", entry)


@pytest.mark.parametrize(
    "failure", ["anonymous_page", "http_error", "login_path", "expired_cookie"]
)
async def test_cookie_alone_cannot_complete_login(connections, failure):
    entry = live(connections, interactive=True)
    if failure == "anonymous_page":
        entry["page"].evaluate.return_value = False
    elif failure == "http_error":
        entry["http_status"] = 403
    elif failure == "login_path":
        entry["page"].url = "https://www.amazon.com.br/ap/signin"
    else:
        entry["context"].cookies.return_value[0]["expires"] = time.time() - 1
    entry["page"].screenshot.return_value = b"jpeg"
    assert (await connections.frame("amazon_br"))["authenticated"] is False
    assert entry["interactive"]
    assert not connections.path("amazon_br").exists()


async def test_frame_automatically_persists_only_confirmed_login(connections):
    entry = live(connections, interactive=True)
    assert await connections.frame("amazon_br") == {
        "status": "connected",
        "authenticated": True,
    }
    assert not entry["interactive"]
    assert connections.read("amazon_br")["status"] == "connected"


async def test_home_event_does_not_save_or_close(connections):
    from panoptes_backend.browser.router import Input

    entry = live(connections, interactive=True, url="https://www.mercadolivre.com.br/")
    connections.live["mercado_livre_br"] = connections.live.pop("amazon_br")
    entry["context"].cookies.return_value = []
    entry["page"].screenshot.return_value = b"jpeg"
    await connections.input("mercado_livre_br", Input(action="home"))
    assert entry["interactive"]
    assert not (await connections.frame("mercado_livre_br"))["authenticated"]
    assert not connections.path("mercado_livre_br").exists()


async def test_direct_mouse_and_keyboard_events(connections):
    from panoptes_backend.browser.router import Input

    entry = live(connections, interactive=True)
    for event in (
        Input(action="down", x=120, y=80),
        Input(action="move", x=160, y=80),
        Input(action="up", x=160, y=80),
        Input(action="key", key="a", modifiers=["Control"]),
        Input(action="scroll", delta=300, delta_x=20),
    ):
        await connections.input("amazon_br", event)
    entry["page"].mouse.down.assert_awaited_once_with(button="left", click_count=1)
    entry["page"].mouse.up.assert_awaited_once_with(button="left", click_count=1)
    entry["page"].keyboard.down.assert_awaited_once_with("Control")
    entry["page"].keyboard.press.assert_awaited_once_with("a")
    entry["page"].keyboard.up.assert_awaited_once_with("Control")
    entry["page"].mouse.wheel.assert_awaited_once_with(20, 300)


async def test_interactive_connection_blocks_worker_and_expires(connections):
    entry = live(connections, interactive=True)
    assert await connections.fetch(
        "amazon_br", "https://www.amazon.com.br/dp/B012345678"
    ) == {"blocked": "connection_in_progress"}
    entry["page"].goto.assert_not_awaited()
    entry["deadline"] = 0
    assert (await connections.status("amazon_br"))["status"] == "disconnected"
    entry["context"].close.assert_awaited_once()


async def test_verification_html_is_never_returned_to_worker(connections):
    entry = live(connections)
    connections.write("amazon_br", {"status": "connected", "storage": {}})
    entry["page"].content.return_value = "validatecaptcha secret login data"
    result = await connections.fetch(
        "amazon_br", "https://www.amazon.com.br/dp/B012345678"
    )
    assert result == {"blocked": "verification_required"}
    assert (await connections.status("amazon_br"))["status"] == "verification_required"
    assert "secret login data" not in str(result)


async def test_ml_captcha_wall_http_200_is_verification_and_not_parser_input(
    connections,
):
    entry = live(connections, url="https://www.mercadolivre.com.br/captcha/wall/logged")
    entry["context"].cookies.return_value = [{"name": "ssid", "value": "test-cookie"}]
    entry["page"].content.return_value = "<h1>Por segurança, complete esta etapa</h1>"
    connections.live["mercado_livre_br"] = entry
    connections.write("mercado_livre_br", {"status": "connected", "storage": {}})
    result = await connections.fetch(
        "mercado_livre_br", "https://lista.mercadolivre.com.br/Sofa-3-lugares"
    )
    assert result == {"blocked": "verification_required", "cause": "captcha"}
    assert (await connections.status("mercado_livre_br"))[
        "status"
    ] == "verification_required"
    assert not await connections.authenticated("mercado_livre_br", entry)


async def test_expired_auth_cookie_requires_reconnection(connections):
    entry = live(connections)
    entry["context"].cookies.return_value = []
    connections.write("amazon_br", {"status": "connected", "storage": {}})
    assert await connections.fetch(
        "amazon_br", "https://www.amazon.com.br/dp/B012345678"
    ) == {"blocked": "reconnect_required"}
    entry["page"].goto.assert_not_awaited()


async def test_authenticated_browser_capture_and_rotating_state(connections):
    entry = live(connections)
    connections.write("amazon_br", {"status": "connected", "storage": {}})
    result = await connections.fetch(
        "amazon_br", "https://www.amazon.com.br/dp/B012345678"
    )
    assert result["body"] == "<html>Produto</html>"
    assert result["status"] == 200
    entry["context"].storage_state.assert_awaited_once_with(indexed_db=True)


async def test_mercado_livre_login_and_capture(connections):
    entry = live(connections, interactive=True, url="https://www.mercadolivre.com.br/")
    connections.live["mercado_livre_br"] = connections.live.pop("amazon_br")
    entry["context"].cookies.return_value = [{"name": "ssid", "value": "ml-session"}]
    assert (await connections.save("mercado_livre_br"))["status"] == "connected"
    result = await connections.fetch(
        "mercado_livre_br", "https://www.mercadolivre.com.br/produto/p/MLB12345678"
    )
    assert result["status"] == 200
    assert permitted("https://auth.mercadolivre.com.br/login", "mercado_livre_br")
    assert not permitted("https://www.amazon.com.br/", "mercado_livre_br")


async def test_mercado_livre_uses_brazilian_account_login_domain(connections):
    from urllib.parse import parse_qs, urlsplit

    from panoptes_backend.browser.router import Input

    login = urlsplit(LOGIN["mercado_livre_br"])
    assert login.hostname == "www.mercadolivre.com"
    assert login.path == "/jms/mlb/lgz/login"
    assert parse_qs(login.query)["go"] == ["https://www.mercadolivre.com.br/"]
    assert permitted(LOGIN["mercado_livre_br"], "mercado_livre_br")
    assert not permitted(
        "https://www.mercadolivre.com.evil.example/", "mercado_livre_br"
    )
    assert not permitted(LOGIN["mercado_livre_br"], "amazon_br")
    entry = live(connections, interactive=True, url=LOGIN["mercado_livre_br"])
    connections.live["mercado_livre_br"] = connections.live.pop("amazon_br")
    await connections.input("mercado_livre_br", Input(action="login"))
    entry["page"].goto.assert_awaited_once_with(
        LOGIN["mercado_livre_br"], wait_until="domcontentloaded", timeout=12000
    )
    entry["context"].cookies.return_value = [
        {"name": "ssid", "value": "present-but-login-not-completed"}
    ]
    assert not await connections.authenticated("mercado_livre_br", entry)
    assert entry["interactive"]
    with pytest.raises(HTTPException):
        await connections.fetch("mercado_livre_br", LOGIN["mercado_livre_br"])


@pytest.mark.parametrize(
    "url",
    [
        "http://www.amazon.com.br/",
        "https://localhost/",
        "https://www.amazon.com.br.evil.com/",
        "https://www.amazon.com.br:444/",
        "https://user:secret@www.amazon.com.br/",
    ],
)
async def test_network_boundaries(connections, url):
    assert not permitted(url, "amazon_br")
    with pytest.raises(HTTPException):
        await connections.fetch("amazon_br", url)


async def test_authentication_admin_and_internal_token(connections, monkeypatch):
    app = create_app()
    app.state.browser_connections = connections
    monkeypatch.setenv("BROWSER_SERVICE_TOKEN", "internal-secret")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/browser-connections")).status_code == 401
        app.dependency_overrides[current_user] = lambda: {
            "email": "someone@example.com"
        }
        assert (await client.get("/browser-connections")).status_code == 403
        app.dependency_overrides[current_user] = lambda: {"email": "admin@panoptes.com"}
        assert (await client.get("/browser-connections")).status_code == 200
        assert (await client.delete("/browser-connections/unknown")).status_code == 422
        payload = {"site": "amazon_br", "url": "https://www.amazon.com.br/"}
        assert (
            await client.post("/internal/browser/fetch", json=payload)
        ).status_code == 403
        result = await client.post(
            "/internal/browser/fetch",
            json=payload,
            headers={"X-Browser-Service-Token": "internal-secret"},
        )
        assert result.json() == {"fallback": True}


async def test_worker_browser_mode_and_disconnected_fallback():
    browser = BrowserClient("http://test", "token")
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = {
        "body": "<html/>",
        "final_url": "https://www.amazon.com.br/",
        "status": 200,
        "media_type": "text/html",
    }
    browser.client.post = AsyncMock(return_value=response)
    captured = await browser.fetch(
        "amazon_br", "https://www.amazon.com.br/", asyncio.Lock(), 0
    )
    assert captured.capture_mode == "browser"
    response.json.return_value["capture_mode"] = "browser_local"
    captured = await browser.fetch(
        "amazon_br", "https://www.amazon.com.br/", asyncio.Lock(), 0
    )
    assert captured.capture_mode == "browser_local"
    response.json.return_value = {"fallback": True}
    assert (
        await browser.fetch(
            "amazon_br", "https://www.amazon.com.br/", asyncio.Lock(), 0
        )
        is None
    )
    await browser.close()


async def test_browser_mode_is_selected_per_source(connections, monkeypatch):
    connections.driver = Mock()
    connections.driver.chromium.launch = AsyncMock(side_effect=[Mock(), Mock()])
    monkeypatch.delenv("BROWSER_MERCADO_LIVRE_HEADLESS", raising=False)
    amazon = await connections.ensure_browser("amazon_br")
    mercado = await connections.ensure_browser("mercado_livre_br")
    assert amazon is not mercado
    assert await connections.ensure_browser("amazon_br") is amazon
    assert await connections.ensure_browser("mercado_livre_br") is mercado
    assert connections.driver.chromium.launch.await_args_list[0].kwargs == {
        "headless": True
    }
    assert connections.driver.chromium.launch.await_args_list[1].kwargs == {
        "headless": False
    }
    monkeypatch.setenv("BROWSER_MERCADO_LIVRE_HEADLESS", "true")
    assert await connections.ensure_browser("mercado_livre_br") is amazon


async def test_failed_browser_launch_does_not_create_live_connection(
    connections, caplog
):
    connections.driver = Mock()
    connections.driver.chromium.launch = AsyncMock(
        side_effect=RuntimeError("display unavailable")
    )
    with pytest.raises(HTTPException) as error:
        await connections.connect("mercado_livre_br")
    assert error.value.status_code == 503
    assert "logs do backend" in error.value.detail
    assert "display unavailable" in caplog.text
    assert "headless=False" in caplog.text
    assert "mercado_livre_br" not in connections.live


async def test_closed_browser_is_relaunched(connections):
    stale = Mock()
    stale.is_connected.return_value = False
    connections.browsers[True] = stale
    connections.driver = Mock()
    replacement = Mock()
    connections.driver.chromium.launch = AsyncMock(return_value=replacement)
    assert await connections.ensure_browser("amazon_br") is replacement
    connections.driver.chromium.launch.assert_awaited_once_with(headless=True)


@pytest.mark.skipif(
    os.getenv("RUN_BROWSER_TESTS") != "1",
    reason="requires installed Playwright Chromium",
)
async def test_real_browser_mirror_input_and_session_restart(tmp_path):
    from panoptes_backend.browser.router import Input

    key = Fernet.generate_key().decode()
    connections = BrowserConnections(tmp_path, key)
    html = '<html><head><meta charset="utf-8"></head><body><input id="text" style="position:absolute;left:10px;top:10px;width:300px;height:40px"><h1>Produto sintético</h1><a href="/logout">Sair</a></body></html>'

    async def synthetic(route):
        await route.fulfill(status=200, content_type="text/html", body=html)

    try:
        entry = await connections.context("amazon_br")
        await entry["context"].route("**/*", synthetic)
        await connections.connect("amazon_br")
        frame = await connections.frame("amazon_br")
        import base64

        assert base64.b64decode(frame["image"]).startswith(b"\xff\xd8")
        popup = await entry["context"].new_page()
        await connections.frame("amazon_br")
        assert entry["page"] is not popup
        await popup.goto("https://www.amazon.com.br/ap/signin")
        await connections.frame("amazon_br")
        assert entry["page"] is popup
        await popup.close()
        await connections.frame("amazon_br")
        assert entry["page"] is not popup
        await connections.input("amazon_br", Input(action="click", x=60, y=30))
        await connections.input(
            "amazon_br", Input(action="text", text="private-password")
        )
        assert await entry["page"].locator("#text").input_value() == "private-password"
        await entry["context"].add_cookies(
            [
                {
                    "name": "at-acbbr",
                    "value": "synthetic-session",
                    "url": "https://www.amazon.com.br/",
                }
            ]
        )
        await connections.input("amazon_br", Input(action="home"))
        await connections.save("amazon_br")
        assert (await connections.frame("amazon_br"))["authenticated"] is True
        assert "private-password" not in str(connections.read("amazon_br"))
    finally:
        await connections.close()

    restart = BrowserConnections(tmp_path, key)
    try:
        entry = await restart.context("amazon_br")
        await entry["context"].route("**/*", synthetic)
        value = await restart.fetch(
            "amazon_br", "https://www.amazon.com.br/dp/B012345678"
        )
        assert value["status"] == 200
        assert "Produto sintético" in value["body"]
        assert (await entry["context"].cookies("https://www.amazon.com.br/"))[0][
            "value"
        ] == "synthetic-session"
    finally:
        await restart.close()
