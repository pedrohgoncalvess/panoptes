from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from panoptes_backend.browser.local import Result
from panoptes_backend.browser.service import (
    HOME,
    PUBLIC_PAGE_READY,
    BrowserConnections,
    permitted,
)


@pytest.fixture(params=["pichau_br", "terabyte_br"])
def retail(request, tmp_path):
    site = request.param
    service = BrowserConnections(tmp_path, Fernet.generate_key().decode())
    page = AsyncMock()
    page.url = HOME[site]
    page.is_closed = Mock(return_value=False)
    page.content.return_value = "<h1>SSD Kingston</h1>"
    page.evaluate.side_effect = lambda script: script == PUBLIC_PAGE_READY
    page.goto.return_value = Mock(status=200, headers={"content-type": "text/html"})
    page.screenshot.return_value = b"jpeg"
    context = AsyncMock()
    context.cookies.return_value = []  # No account cookie is required for these stores.
    context.storage_state.return_value = {"cookies": [], "origins": []}
    live = {
        "page": page,
        "context": context,
        "interactive": False,
        "ready_pages": [page],
    }
    service.live[site] = live
    return site, service, live


async def test_first_public_fetch_saves_access_and_reuses_live_context(retail):
    site, service, live = retail
    first = await service.fetch(site, HOME[site])
    second = await service.fetch(site, HOME[site])
    assert first["body"] == second["body"] == "<h1>SSD Kingston</h1>"
    assert service.read(site)["status"] == "connected"
    assert service.read(site)["access_verified"] is True
    assert live["page"].goto.await_count == 2
    live["context"].close.assert_not_awaited()
    assert b"SSD Kingston" not in service.path(site).read_bytes()


async def test_manual_session_requires_explicit_save_and_supports_restart(retail):
    site, service, live = retail
    live.update(interactive=True, deadline=float("inf"))
    assert "image" in await service.frame(site)
    assert not service.path(site).exists()
    status = await service.save(site)
    assert status["status"] == "connected"
    assert status["requires_login"] is False
    restored = BrowserConnections(service.directory, Fernet.generate_key().decode())
    restored.cipher = service.cipher
    assert restored.read(site)["status"] == "connected"
    assert restored.read(site)["access_verified"] is True
    assert restored.read(site)["account_authenticated"] is False
    assert (await service.frame(site))["session_saved"] is True
    assert (await service.save(site))["status"] == "connected"


@pytest.mark.parametrize("failure", ["captcha", "password", "http403", "empty_page"])
async def test_unverified_page_cannot_be_saved(retail, failure):
    site, service, live = retail
    live.update(interactive=True, deadline=float("inf"))
    if failure == "captcha":
        live["page"].content.return_value = "<title>Just a moment...</title>"
    if failure == "password":
        live["page"].content.return_value = '<form><input type="password"></form>'
    if failure == "http403":
        live["http_status"] = 403
    if failure == "empty_page":
        live["page"].evaluate.side_effect = lambda _: False
    with pytest.raises(HTTPException) as error:
        await service.save(site)
    assert error.value.status_code == 409
    assert not service.path(site).exists()


async def test_challenge_during_collection_returns_no_html_and_stops_next_fetch(retail):
    site, service, live = retail
    live["page"].content.return_value = "<title>Just a moment...</title>"
    result = await service.fetch(site, HOME[site])
    assert result == {"blocked": "verification_required", "cause": "captcha"}
    assert "body" not in result
    assert (await service.fetch(site, HOME[site])) == {
        "blocked": "verification_required"
    }
    live["page"].goto.assert_awaited_once()


async def test_login_form_is_never_returned_to_worker(retail):
    site, service, live = retail
    live["page"].content.return_value = '<h1>Entrar</h1><input type="password">'
    result = await service.fetch(site, HOME[site])
    assert result == {"blocked": "reconnect_required"}
    assert "body" not in result


async def test_local_extension_precedes_backend_browser(retail):
    site, service, _ = retail
    service.write(site, {"status": "connected", "connection_method": "local_extension"})
    service.local.fetch = AsyncMock(
        return_value={"body": "<h1>SSD</h1>", "capture_mode": "browser_local"}
    )
    service.ensure_browser = AsyncMock(
        side_effect=AssertionError("must not launch Chromium")
    )
    assert (await service.fetch(site, HOME[site]))["capture_mode"] == "browser_local"
    service.ensure_browser.assert_not_awaited()


async def test_local_collector_rejects_password_and_cloudflare_dom(retail):
    import asyncio

    site, service, _ = retail
    agent = uuid4()
    service.local.start(site, agent)
    task = asyncio.create_task(service.local.fetch(site, HOME[site]))
    for _ in range(20):
        await asyncio.sleep(0)
        job = service.local.next(site, agent)
        if job["job_id"]:
            break
    service.local.complete(
        site,
        Result(
            agent_id=agent,
            job_id=job["job_id"],
            final_url=HOME[site],
            body="<title>Just a moment...</title>",
        ),
    )
    assert await task == {"blocked": "verification_required", "cause": "captcha"}


def test_source_domains_do_not_expand_to_other_retailers(retail):
    site, _, _ = retail
    assert permitted(HOME[site], site)
    assert permitted("https://challenges.cloudflare.com/turnstile/v0/api.js", site)
    assert not permitted("https://evil.example/", site)
    assert not permitted("https://www.amazon.com.br/", site)


async def test_logged_in_account_page_is_saved_automatically_on_poll(retail):
    site, service, live = retail
    live.update(interactive=True, deadline=float("inf"))
    live["page"].url = HOME[site] + (
        "account" if site == "pichau_br" else "Central.obj"
    )
    live["page"].content.return_value = "<h1>Minha conta</h1><button>Sair</button>"
    live["page"].evaluate.side_effect = lambda _: True
    frame = await service.frame(site)
    assert frame == {
        "status": "connected",
        "authenticated": True,
        "session_saved": True,
    }
    assert service.read(site)["account_authenticated"] is True
    assert live["interactive"] is False
    live["page"].screenshot.assert_not_awaited()
    assert (await service.save(site))["status"] == "connected"


async def test_manual_save_accepts_a_logged_in_account_page(retail):
    site, service, live = retail
    live.update(interactive=True, deadline=float("inf"))
    live["page"].url = HOME[site] + "account"
    live["page"].evaluate.side_effect = lambda _: True
    assert (await service.save(site))["status"] == "connected"
    assert service.read(site)["account_authenticated"] is True


async def test_page_cleanup_failure_does_not_undo_successful_save(retail):
    site, service, live = retail
    live.update(interactive=True, deadline=float("inf"))
    live["page"].goto.side_effect = RuntimeError(
        "navigation failed after storage write"
    )
    assert (await service.save(site))["status"] == "connected"
    assert (await service.frame(site))["session_saved"] is True


async def test_failed_storage_write_keeps_modal_session_open(retail):
    site, service, live = retail
    live.update(interactive=True, deadline=float("inf"))
    live["context"].storage_state.side_effect = RuntimeError("storage failed")
    with pytest.raises(RuntimeError, match="storage failed"):
        await service.save(site)
    assert live["interactive"] is True
    assert not service.path(site).exists()


async def test_concurrent_manual_save_and_automatic_poll_are_idempotent(retail):
    import asyncio

    site, service, live = retail
    live.update(interactive=True, deadline=float("inf"))
    live["page"].evaluate.side_effect = lambda _: True
    frame, saved = await asyncio.gather(service.frame(site), service.save(site))
    assert frame["status"] == saved["status"] == "connected"
    live["context"].storage_state.assert_awaited_once()
