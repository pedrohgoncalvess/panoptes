from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from panoptes_backend.auth.router import current_user
from panoptes_backend.browser.imports import SessionImport
from panoptes_backend.browser.service import BrowserConnections
from panoptes_backend.main import create_app


def payload(domain=".mercadolivre.com.br"):
    return {
        "cookies": [{"name": "ssid", "value": "secret-cookie", "domain": domain}],
        "origins": [
            {
                "origin": "https://www.mercadolivre.com.br",
                "localStorage": [{"name": "token", "value": "secret-local"}],
            }
        ],
    }


def test_session_import_validates_boundaries_and_hides_values():
    value = SessionImport.model_validate(payload())
    assert "secret-cookie" not in repr(value)
    assert "secret-local" not in repr(value)
    assert value.storage("mercado_livre_br")["cookies"][0]["value"] == "secret-cookie"
    for domain in [".amazon.com.br", ".mercadolivre.com.br.evil.test", "localhost"]:
        with pytest.raises(HTTPException):
            SessionImport.model_validate(payload(domain)).storage("mercado_livre_br")
    invalid = payload()
    invalid["origins"][0]["origin"] = "https://www.mercadolivre.com.br/login"
    with pytest.raises(HTTPException):
        SessionImport.model_validate(invalid).storage("mercado_livre_br")


async def test_session_storage_is_origin_scoped_and_not_passed_to_playwright(tmp_path):
    value = payload()
    value["origins"][0]["sessionStorage"] = [
        {"name": "ephemeral", "value": "secret-ephemeral"}
    ]
    imported = SessionImport.model_validate(value)
    assert "secret-ephemeral" not in repr(imported)
    state = imported.storage("mercado_livre_br")
    clean = BrowserConnections.playwright_storage(state)
    assert "sessionStorage" not in clean["origins"][0]
    assert state["origins"][0]["sessionStorage"][0]["value"] == "secret-ephemeral"
    context = AsyncMock()
    await BrowserConnections.restore_session_storage(context, state)
    script = context.add_init_script.call_args.args[0]
    assert "location.origin" in script
    assert "https://www.mercadolivre.com.br" in script
    updated = {"cookies": [], "origins": []}
    BrowserConnections.merge_session_storage(updated, state)
    assert (
        updated["origins"][0]["sessionStorage"] == state["origins"][0]["sessionStorage"]
    )


@pytest.mark.parametrize("authenticated", [True, False])
async def test_import_only_replaces_previous_encrypted_session_after_verification(
    tmp_path, authenticated, monkeypatch
):
    service = BrowserConnections(tmp_path, Fernet.generate_key().decode())
    previous = {
        "status": "connected",
        "storage": {"cookies": [], "origins": []},
        "saved_at": "old",
    }
    service.write("mercado_livre_br", previous)
    context = AsyncMock()
    context.new_page.return_value = AsyncMock()
    context.new_page.return_value.is_closed = Mock(return_value=False)
    state = SessionImport.model_validate(payload()).storage("mercado_livre_br")
    context.storage_state.return_value = state
    browser = AsyncMock()
    browser.new_context.return_value = context
    service.ensure_browser = AsyncMock(return_value=browser)
    service.navigate = AsyncMock()
    service.authenticated = AsyncMock(return_value=authenticated)
    monkeypatch.setattr("panoptes_backend.browser.service.asyncio.sleep", AsyncMock())
    if authenticated:
        assert (await service.import_session("mercado_livre_br", state))[
            "status"
        ] == "connected"
        assert service.read("mercado_livre_br")["storage"] == state
        assert (await service.status("mercado_livre_br"))[
            "connection_method"
        ] == "extension"
        assert b"secret-cookie" not in service.path("mercado_livre_br").read_bytes()
        context.close.assert_not_awaited()
        assert (await service.context("mercado_livre_br"))["context"] is context
        browser.new_context.assert_awaited_once()
    else:
        with pytest.raises(HTTPException) as error:
            await service.import_session("mercado_livre_br", state)
        assert error.value.status_code == 409
        assert service.read("mercado_livre_br") == previous
        context.close.assert_awaited_once()


async def test_import_endpoint_requires_admin_and_rejects_foreign_state(tmp_path):
    app = create_app()
    app.state.browser_connections = BrowserConnections(
        tmp_path, Fernet.generate_key().decode()
    )
    app.state.browser_connections.import_session = AsyncMock(
        return_value={"status": "connected"}
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        path = "/browser-connections/mercado_livre_br/import"
        assert (await client.post(path, json=payload())).status_code == 401
        app.dependency_overrides[current_user] = lambda: {
            "email": "someone@example.com"
        }
        assert (await client.post(path, json=payload())).status_code == 403
        app.dependency_overrides[current_user] = lambda: {"email": "admin@panoptes.com"}
        assert (await client.post(path, json=payload(".evil.test"))).status_code == 422
        assert (await client.post(path, json=payload())).status_code == 200
        app.state.browser_connections.import_session.assert_awaited_once()
