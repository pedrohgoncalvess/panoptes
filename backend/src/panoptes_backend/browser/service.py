import asyncio
import base64
import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from fastapi import HTTPException
from panoptes_contracts.sources import SOURCES, captcha_page, login_page

from .local import LocalCollector

logger = logging.getLogger(__name__)

HOME = {
    "amazon_br": "https://www.amazon.com.br/",
    "mercado_livre_br": "https://www.mercadolivre.com.br/",
    "pichau_br": "https://www.pichau.com.br/",
    "terabyte_br": "https://www.terabyteshop.com.br/",
}
PUBLIC_CONNECTION_SITES = {"pichau_br", "terabyte_br"}
LOGIN = {
    "pichau_br": "https://www.pichau.com.br/account",
    "terabyte_br": "https://www.terabyteshop.com.br/Central.obj",
    "amazon_br": "https://www.amazon.com.br/ap/signin?openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2Fwww.amazon.com.br%2F&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.assoc_handle=brflex&openid.mode=checkid_setup&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0",
    "mercado_livre_br": "https://www.mercadolivre.com/jms/mlb/lgz/login?platform_id=ML&go=https%3A%2F%2Fwww.mercadolivre.com.br%2F&loginType=explicit",
}
DOMAINS = {
    "pichau_br": ("pichau.com.br", "challenges.cloudflare.com"),
    "terabyte_br": ("terabyteshop.com.br", "challenges.cloudflare.com"),
    "amazon_br": (
        "amazon.com.br",
        "media-amazon.com",
        "ssl-images-amazon.com",
        "amazon.com",
        "a2z.com",
    ),
    "mercado_livre_br": (
        "mercadolivre.com.br",
        "mercadolivre.com",
        "mercadolibre.com",
        "mlstatic.com",
        "mercadopago.com.br",
    ),
}
AUTH_COOKIES = {"amazon_br": {"at-acbbr", "at-main"}, "mercado_livre_br": {"ssid"}}
PUBLIC_PAGE_READY = """() => {
    if (document.readyState === 'loading' || !document.body?.innerText.trim()) return false;
    if (document.querySelector('input[type="password"]')) return false;
    return !!document.querySelector('h1, a[href*="/produto/"], [data-cy="list-product"], #main-content');
}"""
RETAIL_ACCOUNT_AUTHENTICATED = """() => {
    const visible = el => !!el && !el.closest('[hidden], [aria-hidden="true"]')
        && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
    if (document.readyState === 'loading' || !document.body?.innerText.trim()) return false;
    if ([...document.querySelectorAll('input[type="password"]')].some(visible)) return false;
    const norm = text => (text || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')
        .toLowerCase().replace(/\\s+/g, ' ').trim();
    const actions = [...document.querySelectorAll('a[href], button, [role="button"]')];
    if (actions.some(el => visible(el) && (
        /(?:^|[/?=&])(?:logout|signout|logoff)(?:[/?=&]|$)/i.test(el.getAttribute('href') || '')
        || /^(?:sair|sair da conta|encerrar sessao|logout|sign out)$/.test(norm(el.innerText || el.getAttribute('aria-label')))
    ))) return true;
    const names = document.querySelectorAll('[data-cy="customer-name"], [data-testid="customer-name"], [class*="customer_name"], [class*="customerName"]');
    if ([...names].some(el => visible(el) && norm(el.innerText)
        && !/^(?:minha conta|cliente|visitante|entrar|entre|faca login)$/.test(norm(el.innerText)))) return true;
    return [...document.querySelectorAll('header a, header button, nav a, nav button, .minha-conta, .minha_conta')]
        .some(el => visible(el) && /^(?:ola|bem vindo)[,!: ]+\\S+/.test(norm(el.innerText))
            && !/\\b(?:entre|entrar|login|cadastre|visitante|identifique|seja|sejam)\\b/.test(norm(el.innerText))
            && !/^(?:ola|bem vindo)[,!: ]+(?:cliente|usuario)$/.test(norm(el.innerText)));
}"""
AUTHENTICATED_PAGE = """site => {
    if (document.readyState === 'loading' || !document.body?.innerText.trim()) return false;
    if (document.querySelector('input[type="password"], #captchacharacters, form[action*="validateCaptcha"]')) return false;
    const text = document.body.innerText.toLowerCase();
    if (/not a robot|algo deu errado|algo salió mal|hubo un error|access denied|não foi possível acessar/.test(text)) return false;
    const logout = [...document.querySelectorAll('a[href]')].some(a => /\\/(?:signout|logout|jms\\/mlb\\/lgz\\/logout)(?:[/?]|$)/i.test(a.getAttribute('href')));
    if (logout) return true;
    if (site === 'amazon_br') {
        const greeting = document.querySelector('#nav-link-accountList-nav-line-1')?.textContent?.trim();
        return !!greeting && /^(olá|hello),?\\s+\\S+/i.test(greeting) && !/faça|sign in|identifique|entrar/i.test(greeting);
    }
    return [...document.querySelectorAll('.nav-header-username, .nav-header-user-menu__nickname, .nav-menu-user-info .nav-menu-user-info__name')]
        .some(el => !!el.textContent?.trim() && !/entre|entrar|crie|ingress|inicia/i.test(el.textContent));
}"""
VERIFICATION_PATHS = (
    "/captcha/",
    "/ap/",
    "/login",
    "/auth/",
    "/registration",
    "/account-verification",
    "/gz/verification",
)


def permitted(url, site):
    parts = urlsplit(url)
    host = parts.hostname or ""
    domains = DOMAINS[site] + ("google.com", "gstatic.com", "recaptcha.net")
    return (
        parts.scheme == "https"
        and parts.port in (None, 443)
        and not parts.username
        and not parts.password
        and any(host == domain or host.endswith("." + domain) for domain in domains)
    )


class BrowserConnections:
    """One context per source, serialized between manual operation and workers.

    Only encrypted storage_state is written. No browser profile, password manager,
    traces, videos, screenshots or request logs are persisted.
    """

    def __init__(self, directory, key):
        self.directory = Path(directory)
        self.cipher = Fernet(key.encode())
        self.locks = {site: asyncio.Lock() for site in SOURCES}
        self.live = {}
        self.driver = None
        self.browsers = {}
        self.launch_lock = asyncio.Lock()
        self.local = LocalCollector()

    def path(self, site):
        if site not in SOURCES:
            raise HTTPException(404, "Fonte não encontrada.")
        return self.directory / f"{site}.session"

    def read(self, site):
        path = self.path(site)
        if not path.exists():
            return {"status": "disconnected"}
        try:
            return json.loads(self.cipher.decrypt(path.read_bytes()))
        except Exception:
            raise HTTPException(
                503,
                "Não foi possível abrir a sessão. Confira a chave ou desconecte para criar outra.",
            ) from None

    def write(self, site, value):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.path(site)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(self.cipher.encrypt(json.dumps(value).encode()))
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    async def expire(self, site):
        live = self.live.get(site)
        if live and live["interactive"] and time.monotonic() > live["deadline"]:
            await self.drop(site)

    async def drop(self, site):
        live = self.live.pop(site, None)
        if live:
            await live["context"].close()

    async def status(self, site):
        async with self.locks[site]:
            await self.expire(site)
            try:
                state = self.read(site)
            except HTTPException as error:
                if error.status_code != 503:
                    raise
                state = {"status": "reconnect_required"}
            interactive = bool(self.live.get(site, {}).get("interactive"))
            local_mode = state.get("connection_method") == "local_extension"
            return {
                "site": site,
                "name": SOURCES[site].name,
                "status": "local_browser_unavailable"
                if local_mode and not self.local.online(site)
                else "connecting"
                if interactive
                else state["status"],
                "interactive": interactive,
                "saved_at": state.get("saved_at"),
                "connection_method": state.get("connection_method", "browser")
                if state.get("saved_at")
                else None,
                "requires_login": site not in PUBLIC_CONNECTION_SITES,
                "access_verified": state.get("access_verified", False),
                "account_authenticated": state.get("account_authenticated", False),
            }

    async def start_local(self, site, agent_id):
        from datetime import UTC, datetime

        async with self.locks[site]:
            await self.drop(site)
            state = self.read(site)
            state.update(
                status="connected",
                connection_method="local_extension",
                saved_at=datetime.now(UTC).isoformat(),
            )
            self.write(site, state)
            self.local.start(site, agent_id)
        return await self.status(site)

    async def ensure_browser(self, site):
        headless = (
            site != "mercado_livre_br"
            or os.getenv("BROWSER_MERCADO_LIVRE_HEADLESS", "false").lower() == "true"
        )
        if site in PUBLIC_CONNECTION_SITES:
            headless = os.getenv("BROWSER_RETAIL_HEADLESS", "false").lower() == "true"
        async with self.launch_lock:
            if (
                headless in self.browsers
                and self.browsers[headless].is_connected() is False
            ):
                del self.browsers[headless]
            if headless not in self.browsers:
                try:
                    if self.driver is None:
                        from playwright.async_api import async_playwright

                        self.driver = await async_playwright().start()
                    self.browsers[headless] = await self.driver.chromium.launch(
                        headless=headless
                    )
                except Exception:
                    logger.exception(
                        "Chromium startup failed: site=%s headless=%s DISPLAY=%s HOME=%s",
                        site,
                        headless,
                        os.getenv("DISPLAY", "unset"),
                        os.getenv("HOME", "unset"),
                    )
                    raise HTTPException(
                        503,
                        "Não foi possível iniciar o navegador. A causa foi registrada nos logs do backend.",
                    ) from None
            return self.browsers[headless]

    async def context(self, site):
        if site in self.live:
            if self.live[site]["page"].is_closed() is False:
                return self.live[site]
            await self.drop(site)
        browser = await self.ensure_browser(site)
        state = self.read(site)
        try:
            context = await browser.new_context(
                storage_state=self.playwright_storage(state.get("storage")),
                viewport={"width": 1280, "height": 800},
                locale="pt-BR",
                extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5"},
                timezone_id="America/Sao_Paulo",
                accept_downloads=False,
                service_workers="block",
            )
        except Exception:
            logger.exception("Chromium context creation failed: site=%s", site)
            raise HTTPException(
                503,
                "Não foi possível criar a janela do navegador. Verifique a tela virtual e tente novamente.",
            ) from None
        context.set_default_timeout(15000)
        await self.restore_session_storage(context, state.get("storage", {}))

        async def route(request):
            if permitted(request.request.url, site):
                await request.continue_()
            else:
                await request.abort()

        await context.route("**/*", route)
        page = await context.new_page()

        # Login flows may open a new window. Mirror only the latest page.
        def new_page(opened):
            def ready():
                if (
                    site in self.live
                    and opened.url != "about:blank"
                    and permitted(opened.url, site)
                ):
                    self.live[site]["page"] = opened
                    self.live[site]["ready_pages"].append(opened)
                    self.live[site]["http_status"] = self.live[site]["page_status"].get(
                        opened, 200
                    )

            opened.on("domcontentloaded", ready)
            opened.on("close", lambda: self.restore_page(site))

        context.on("page", new_page)
        live = {
            "context": context,
            "page": page,
            "interactive": False,
            "ready_pages": [page],
            "page_status": {},
        }

        def response_received(response):
            if (
                response.request.is_navigation_request()
                and response.frame == response.frame.page.main_frame
            ):
                live["page_status"][response.frame.page] = response.status
            if (
                response.request.is_navigation_request()
                and response.frame == live["page"].main_frame
            ):
                live["http_status"] = response.status
                live["navigation_error"] = (
                    "O Mercado Livre recusou o acesso (HTTP 403). A sessão ainda não foi autenticada."
                    if site == "mercado_livre_br" and response.status == 403
                    else f"O site retornou HTTP {response.status}. A sessão ainda não foi autenticada."
                    if response.status >= 400
                    else ""
                )

        context.on("response", response_received)
        self.live[site] = live
        return live

    def restore_page(self, site):
        live = self.live.get(site)
        if live:
            for page in reversed(live.get("ready_pages", [])):
                if (
                    not page.is_closed()
                    and page.url != "about:blank"
                    and permitted(page.url, site)
                ):
                    live["page"] = page
                    live["http_status"] = live.get("page_status", {}).get(
                        page, live.get("http_status", 200)
                    )
                    return

    async def navigate(self, live, url):
        from playwright.async_api import TimeoutError as NavigationTimeout

        live["navigation_error"] = ""
        try:
            response = await live["page"].goto(
                url, wait_until="domcontentloaded", timeout=12000
            )
            if response:
                live["http_status"] = response.status
            if response and response.status >= 400:
                live["http_status"] = response.status
                live["navigation_error"] = (
                    "O Mercado Livre recusou o acesso (HTTP 403). A sessão ainda não foi autenticada."
                    if response.status == 403 and "mercadolivre" in url
                    else f"O site retornou HTTP {response.status}. A sessão ainda não foi autenticada."
                )
        except NavigationTimeout:
            live["navigation_error"] = (
                "O site está demorando para carregar. Aguarde ou tente abrir o login novamente."
            )
        except Exception:
            live["navigation_error"] = (
                "Não foi possível carregar a página do site. Tente abrir o login novamente."
            )

    async def authenticated(self, site, live):
        if live.get("http_status", 200) >= 400 or live.get("navigation_error"):
            return False
        parts = urlsplit(live["page"].url)
        if parts.hostname not in SOURCES[site].page_hosts or any(
            p in parts.path.lower() for p in VERIFICATION_PATHS
        ):
            return False
        if site in PUBLIC_CONNECTION_SITES:
            body = await live["page"].content()
            if captcha_page(live["page"].url, body) or login_page(
                live["page"].url, body
            ):
                return False
            try:
                return await live["page"].evaluate(PUBLIC_PAGE_READY) is True
            except Exception:
                return False
        cookies = await live["context"].cookies(HOME[site])
        now = time.time()
        if not any(
            c["name"] in AUTH_COOKIES[site]
            and c["value"]
            and (c.get("expires", -1) == -1 or c.get("expires", -1) > now)
            for c in cookies
        ):
            return False
        try:
            return await live["page"].evaluate(AUTHENTICATED_PAGE, site) is True
        except Exception:
            return False

    async def retail_logged_in(self, site, live):
        """Public access alone must never trigger an automatic account save."""
        if (
            live.get("http_status", 200) >= 400
            or live.get("navigation_error")
            or urlsplit(live["page"].url).hostname not in SOURCES[site].page_hosts
            or any(
                p in urlsplit(live["page"].url).path.lower() for p in VERIFICATION_PATHS
            )
        ):
            return False
        try:
            if captcha_page(live["page"].url, await live["page"].content()):
                return False
            return await live["page"].evaluate(RETAIL_ACCOUNT_AUTHENTICATED) is True
        except Exception:
            return False

    async def persist(self, site, live, *, account_authenticated=None):
        from datetime import UTC, datetime

        self.write(
            site,
            {
                "status": "connected",
                "saved_at": datetime.now(UTC).isoformat(),
                "storage": await live["context"].storage_state(indexed_db=True),
                "access_verified": site in PUBLIC_CONNECTION_SITES,
                "account_authenticated": site not in PUBLIC_CONNECTION_SITES
                if account_authenticated is None
                else account_authenticated,
            },
        )
        live["interactive"] = False
        # Clear login/password fields from the live DOM; next worker navigates again.
        try:
            await live["page"].goto("about:blank", timeout=5000)
        except Exception:
            # The state is already committed; cleanup must not turn a successful save into HTTP 500.
            logger.warning(
                "Saved browser state; clearing the live page failed: site=%s", site
            )

    async def connect(self, site):
        self.local.stop(site)
        async with self.locks[site]:
            await self.expire(site)
            state = self.read(site)
            if state.get("connection_method") == "local_extension":
                state.update(connection_method="browser", status="reconnect_required")
                self.write(site, state)
            live = await self.context(site)
            live.update(interactive=True, deadline=time.monotonic() + 900)
            await self.navigate(
                live, HOME[site] if site in PUBLIC_CONNECTION_SITES else LOGIN[site]
            )
        return await self.status(site)

    async def import_session(self, site, storage):
        async with self.locks[site]:
            browser = await self.ensure_browser(site)
            context = await browser.new_context(
                storage_state=self.playwright_storage(storage),
                viewport={"width": 1280, "height": 800},
                locale="pt-BR",
                extra_http_headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5"},
                timezone_id="America/Sao_Paulo",
                accept_downloads=False,
                service_workers="block",
            )
            accepted = False
            try:
                await self.restore_session_storage(context, storage)

                async def route(request):
                    if permitted(request.request.url, site):
                        await request.continue_()
                    else:
                        await request.abort()

                await context.route("**/*", route)
                page = await context.new_page()
                candidate = {
                    "context": context,
                    "page": page,
                    "interactive": False,
                    "ready_pages": [page],
                    "page_status": {},
                }
                await self.navigate(candidate, HOME[site])
                # Rendering can finish after DOMContentLoaded.
                for attempt in range(6):
                    if await self.authenticated(site, candidate):
                        break
                    if attempt == 5:
                        raise HTTPException(
                            409,
                            "O site não confirmou a sessão no Panoptes. Verifique seu login ou use o navegador espelhado. A sessão anterior foi preservada.",
                        )
                    await asyncio.sleep(0.5)
                from datetime import UTC, datetime

                imported = {
                    "status": "connected",
                    "connection_method": "extension",
                    "saved_at": datetime.now(UTC).isoformat(),
                    "storage": await context.storage_state(indexed_db=True),
                    "access_verified": site in PUBLIC_CONNECTION_SITES,
                }
                self.merge_session_storage(imported["storage"], storage)
                self.write(site, imported)
                await self.drop(site)
                self.local.stop(site)
                self.live[site] = candidate
                accepted = True
            finally:
                if not accepted:
                    await context.close()
        return await self.status(site)

    @staticmethod
    def playwright_storage(storage):
        if not storage:
            return storage
        return {
            "cookies": storage.get("cookies", []),
            "origins": [
                {k: v for k, v in origin.items() if k != "sessionStorage"}
                for origin in storage.get("origins", [])
            ],
        }

    @staticmethod
    def merge_session_storage(target, source):
        for origin in source.get("origins", []):
            if "sessionStorage" not in origin:
                continue
            destination = next(
                (o for o in target["origins"] if o["origin"] == origin["origin"]), None
            )
            if destination is None:
                destination = {"origin": origin["origin"], "localStorage": []}
                target["origins"].append(destination)
            destination["sessionStorage"] = origin["sessionStorage"]

    @staticmethod
    async def restore_session_storage(context, storage):
        values = {
            o["origin"]: o["sessionStorage"]
            for o in storage.get("origins", [])
            if o.get("sessionStorage")
        }
        if values:
            await context.add_init_script(
                "(() => { const states = "
                + json.dumps(values)
                + "; for (const item of states[location.origin] || []) {"
                "if (sessionStorage.getItem(item.name) === null) sessionStorage.setItem(item.name, item.value); } })();"
            )

    async def frame(self, site):
        async with self.locks[site]:
            await self.expire(site)
            live = self.live.get(site)
            if (
                live
                and not live["interactive"]
                and self.read(site)["status"] == "connected"
            ):
                return {
                    "status": "connected",
                    "authenticated": site not in PUBLIC_CONNECTION_SITES
                    or self.read(site).get("account_authenticated", False),
                    **(
                        {"access_verified": True, "session_saved": True}
                        if site in PUBLIC_CONNECTION_SITES
                        else {}
                    ),
                }
            if not live or not live["interactive"]:
                raise HTTPException(409, "Abra a conexão novamente.")
            self.restore_page(site)
            logged_in = (
                await self.retail_logged_in(site, live)
                if site in PUBLIC_CONNECTION_SITES
                else await self.authenticated(site, live)
            )
            if logged_in:
                await self.persist(site, live, account_authenticated=True)
                return {
                    "status": "connected",
                    "authenticated": True,
                    **(
                        {"session_saved": True}
                        if site in PUBLIC_CONNECTION_SITES
                        else {}
                    ),
                }
            image = await live["page"].screenshot(type="jpeg", quality=75, timeout=5000)
            return {
                "image": base64.b64encode(image).decode(),
                "width": 1280,
                "height": 800,
                "authenticated": False,
                "notice": live.get("navigation_error", ""),
            }

    async def input(self, site, value):
        async with self.locks[site]:
            await self.expire(site)
            live = self.live.get(site)
            if not live or not live["interactive"]:
                raise HTTPException(409, "Abra a conexão novamente.")
            page = live["page"]
            if value.action == "click":
                await page.mouse.click(value.x, value.y)
            elif value.action == "text":
                await page.keyboard.insert_text(value.text.get_secret_value())
            elif value.action == "key":
                key = value.key.get_secret_value()
                for modifier in value.modifiers:
                    await page.keyboard.down(modifier)
                try:
                    await page.keyboard.press(key)
                finally:
                    for modifier in reversed(value.modifiers):
                        await page.keyboard.up(modifier)
            elif value.action == "scroll":
                await page.mouse.wheel(value.delta_x, value.delta)
            elif value.action == "move":
                await page.mouse.move(value.x, value.y)
            elif value.action in ("down", "up"):
                if value.action == "down":
                    for modifier in value.modifiers:
                        await page.keyboard.down(modifier)
                await page.mouse.move(value.x, value.y)
                await getattr(page.mouse, value.action)(
                    button=value.button, click_count=value.click_count
                )
                if value.action == "up":
                    for modifier in reversed(value.modifiers):
                        await page.keyboard.up(modifier)
            elif value.action == "release":
                for modifier in ("Shift", "Control", "Alt", "Meta"):
                    await page.keyboard.up(modifier)
                for button in ("left", "right", "middle"):
                    await page.mouse.up(button=button)
            elif value.action in ("home", "login"):
                await self.navigate(
                    live, HOME[site] if value.action == "home" else LOGIN[site]
                )
            return {"ok": True}

    async def save(self, site):
        async with self.locks[site]:
            await self.expire(site)
            live = self.live.get(site)
            if not live:
                raise HTTPException(409, "Abra a conexão novamente.")
            if not live["interactive"]:
                if self.read(site)["status"] != "connected":
                    raise HTTPException(409, "Abra a conexão novamente.")
            else:
                self.restore_page(site)
                logged_in = (
                    await self.retail_logged_in(site, live)
                    if site in PUBLIC_CONNECTION_SITES
                    else await self.authenticated(site, live)
                )
                if not logged_in and not (
                    site in PUBLIC_CONNECTION_SITES
                    and await self.authenticated(site, live)
                ):
                    raise HTTPException(
                        409,
                        "O acesso à loja ainda não foi confirmado. Conclua a verificação e volte à página inicial."
                        if site in PUBLIC_CONNECTION_SITES
                        else "Sessão de login não detectada. Conclua o login no site antes de salvar.",
                    )
                await self.persist(site, live, account_authenticated=logged_in)
        return await self.status(site)

    async def cancel(self, site):
        async with self.locks[site]:
            await self.drop(site)
        return await self.status(site)

    async def disconnect(self, site):
        self.local.stop(site)
        async with self.locks[site]:
            await self.drop(site)
            self.path(site).unlink(missing_ok=True)
        return await self.status(site)

    async def fetch(self, site, url):
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or parts.hostname not in SOURCES[site].page_hosts
            or parts.port not in (None, 443)
            or parts.username
            or parts.password
        ):
            raise HTTPException(422, "URL fora da fonte permitida.")
        if site not in HOME:
            from .public import capture_public

            async with self.locks[site]:
                browser = await self.ensure_browser(site)
                return await capture_public(browser, site, url)
        if self.read(site).get("connection_method") == "local_extension":
            return await self.local.fetch(site, url)
        async with self.locks[site]:
            await self.expire(site)
            state = self.read(site)
            if self.live.get(site, {}).get("interactive"):
                return {"blocked": "connection_in_progress"}
            if state["status"] == "disconnected":
                if site not in PUBLIC_CONNECTION_SITES:
                    return {"fallback": True}
            elif state["status"] != "connected":
                return {"blocked": state["status"]}
            live = await self.context(site)
            page = live["page"]
            cookies = await live["context"].cookies(HOME[site])
            if site not in PUBLIC_CONNECTION_SITES and not any(
                c["name"] in AUTH_COOKIES[site] and c["value"] for c in cookies
            ):
                state["status"] = "reconnect_required"
                self.write(site, state)
                return {"blocked": "reconnect_required"}
            try:
                response = await page.goto(
                    url, wait_until="domcontentloaded", timeout=45000
                )
                final = urlsplit(page.url)
                status = response.status if response else 503
                body = await page.content()
                if (
                    site in PUBLIC_CONNECTION_SITES
                    and status == 200
                    and not captcha_page(page.url, body)
                ):
                    from .public import wait_for_public_page

                    await wait_for_public_page(page)
                    body = await page.content()
                lowered = body.lower()
                blocked = (
                    "verification_required"
                    if captcha_page(page.url, body)
                    else "reconnect_required"
                    if login_page(page.url, body)
                    or final.hostname not in SOURCES[site].page_hosts
                    or any(p in final.path.lower() for p in VERIFICATION_PATHS)
                    or status == 401
                    else "verification_required"
                    if status == 403
                    or any(
                        p in lowered
                        for p in ("validatecaptcha", "captchacharacters", "not a robot")
                    )
                    else "rate_limited"
                    if status == 429
                    else None
                )
                if blocked:
                    state["status"] = blocked
                    self.write(site, state)
                    # Do not return authenticated login/verification HTML to capture storage.
                    return (
                        {"blocked": blocked, "cause": "captcha"}
                        if captcha_page(page.url, body)
                        else {"blocked": blocked}
                    )
                if len(body.encode()) > 6_000_000:
                    raise HTTPException(502, "Página excede o limite de captura.")
                previous_storage = state.get("storage", {})
                state["storage"] = await live["context"].storage_state(indexed_db=True)
                self.merge_session_storage(state["storage"], previous_storage)
                if (
                    site in PUBLIC_CONNECTION_SITES
                    and status == 200
                    and await self.authenticated(site, live)
                ):
                    from datetime import UTC, datetime

                    state.update(
                        status="connected",
                        access_verified=True,
                        saved_at=datetime.now(UTC).isoformat(),
                    )
                self.write(site, state)
                media_type = (
                    response.headers.get("content-type", "text/html")
                    .split(";", 1)[0]
                    .lower()
                    if response
                    else "text/html"
                )
                return {
                    "body": body,
                    "final_url": page.url,
                    "status": status,
                    "media_type": media_type,
                    "capture_mode": "browser",
                }
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(
                    502, "Falha ao navegar na fonte conectada."
                ) from None

    async def close(self):
        for site in SOURCES:
            self.local.stop(site)
        for site in list(self.live):
            await self.drop(site)
        for browser in self.browsers.values():
            await browser.close()
        self.browsers.clear()
        if self.driver:
            await self.driver.stop()
            self.driver = None

    async def cleanup_loop(self):
        while True:
            await asyncio.sleep(30)
            for site in SOURCES:
                async with self.locks[site]:
                    await self.expire(site)
