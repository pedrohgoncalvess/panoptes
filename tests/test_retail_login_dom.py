"""Exercise account detection against a real DOM, never real credentials."""

import os

import pytest
from cryptography.fernet import Fernet
from panoptes_backend.browser.service import (
    RETAIL_ACCOUNT_AUTHENTICATED,
    BrowserConnections,
)


@pytest.mark.skipif(
    os.getenv("RUN_BROWSER_TESTS") != "1",
    reason="requires installed Playwright Chromium",
)
async def test_account_detection_in_chromium_and_encrypted_session_save(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("BROWSER_RETAIL_HEADLESS", "true")
    service = BrowserConnections(tmp_path, Fernet.generate_key().decode())
    samples = [
        ('<h1>Pichau</h1><header><a href="/account">Minha conta</a></header>', False),
        ('<h1>Minha conta</h1><input type="password"><button>Entrar</button>', False),
        (
            '<h1>Entrar</h1><a style="display:none" href="/account/logout">Sair</a>',
            False,
        ),
        ("<header><a>Olá, Entre ou Cadastre-se</a></header>", False),
        ("<header><a>Olá, seja bem-vindo</a></header>", False),
        ("<header><a>Olá, Cliente</a></header>", False),
        ('<h1>Minha conta</h1><a href="/account/logout">Sair</a>', True),
        ("<h1>Minha conta</h1><button>Sair</button>", True),
        ("<header><a>Olá, Cliente Teste</a></header>", True),
    ]
    try:
        live = await service.context("pichau_br")
        page = live["page"]
        for html, expected in samples:
            await page.set_content(html)
            assert await page.evaluate(RETAIL_ACCOUNT_AUTHENTICATED) is expected, html

        async def fixture(route):
            await route.fulfill(
                status=200,
                content_type="text/html",
                body="<h1>Minha conta</h1><button>Sair</button>",
            )

        await live["context"].route("https://www.pichau.com.br/**", fixture)
        await page.goto("https://www.pichau.com.br/account")
        live.update(interactive=True, deadline=float("inf"))
        frame = await service.frame("pichau_br")
        assert frame["authenticated"] is True and frame["session_saved"] is True
        assert service.read("pichau_br")["account_authenticated"] is True
        assert (await service.save("pichau_br"))["status"] == "connected"
    finally:
        await service.close()
