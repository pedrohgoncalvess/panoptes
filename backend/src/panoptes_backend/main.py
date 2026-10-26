import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from panoptes_ai.runtime import ai_runtime
from panoptes_database.config import load_database_settings
from panoptes_database.session import create_database, unit_of_work

from .alerts.delivery import run as deliver_webhooks
from .alerts.router import router as alerts_router
from .auth.mcp_keys import router as mcp_keys_router
from .auth.router import current_user
from .auth.router import router as auth_router
from .auth.security import load_secret
from .auth.services import seed_admin
from .browser.router import internal_router as browser_internal_router
from .browser.router import router as browser_router
from .browser.service import BrowserConnections
from .catalog.categories import router as categories_router
from .catalog.product_search import ProductSearch
from .catalog.router import router as catalog_router
from .catalog.search import router as search_router
from .catalog.taxonomy import router as taxonomy_router
from .contracts.router import router as contracts_router
from .core.handlers import install_handlers
from .core.router import router as health_router
from .management.logs import router as logs_router
from .management.router import router as management_router
from .management.storage_cleanup import run as cleanup_deleted_assets
from .routines.router import router as routines_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine, sessions = create_database(load_database_settings())
    app.state.engine = engine
    app.state.sessions = sessions
    browser_cleanup = None
    product_index = None
    asset_cleanup = None
    webhook_delivery = None
    try:
        app.state.jwt_secret = load_secret()
        app.state.browser_connections = (
            BrowserConnections(
                os.getenv("BROWSER_SESSION_DIR", ".browser-sessions"),
                os.environ["BROWSER_SESSION_KEY"],
            )
            if os.getenv("BROWSER_SESSION_KEY")
            else None
        )
        if app.state.browser_connections:
            browser_cleanup = asyncio.create_task(
                app.state.browser_connections.cleanup_loop()
            )
        async with unit_of_work(sessions) as session:
            await seed_admin(session)
        async with ai_runtime(sessions) as ai:
            app.state.ai = ai
            app.state.product_search = ProductSearch(sessions, ai)
            product_index = asyncio.create_task(app.state.product_search.run())
            asset_cleanup = asyncio.create_task(cleanup_deleted_assets(sessions))
            webhook_delivery = asyncio.create_task(deliver_webhooks(sessions))
            try:
                yield
            finally:
                product_index.cancel()
                await asyncio.gather(product_index, return_exceptions=True)
                product_index = None
    finally:
        if webhook_delivery:
            webhook_delivery.cancel()
            await asyncio.gather(webhook_delivery, return_exceptions=True)
        if asset_cleanup:
            asset_cleanup.cancel()
            await asyncio.gather(asset_cleanup, return_exceptions=True)
        if product_index:
            product_index.cancel()
            await asyncio.gather(product_index, return_exceptions=True)
        if browser_cleanup:
            browser_cleanup.cancel()
            await asyncio.gather(browser_cleanup, return_exceptions=True)
        if getattr(app.state, "browser_connections", None):
            await app.state.browser_connections.close()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Panoptes management API",
        version="0.2.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    install_handlers(app)
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(mcp_keys_router)
    app.include_router(browser_router)
    app.include_router(browser_internal_router)
    for router in (
        contracts_router,
        catalog_router,
        search_router,
        categories_router,
        taxonomy_router,
        routines_router,
        alerts_router,
        management_router,
        logs_router,
    ):
        app.include_router(router, dependencies=[Depends(current_user)])

    @app.get(
        "/openapi.json", dependencies=[Depends(current_user)], include_in_schema=False
    )
    async def openapi():
        return app.openapi()

    return app


app = create_app()
