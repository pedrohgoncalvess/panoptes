import hmac
import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from panoptes_contracts.sources import BrowserSourceId, SourceId
from pydantic import BaseModel, Field, SecretStr

from ..auth.router import current_user
from .imports import SESSION_DOMAINS, SessionImport
from .local import Agent, Result

router = APIRouter(prefix="/browser-connections", tags=["browser-connections"])
internal_router = APIRouter(prefix="/internal/browser", tags=["internal-browser"])


async def administrator(user=Depends(current_user)):
    if user.get("role") != "admin" and user.get("email") != "admin@panoptes.com":
        raise HTTPException(
            403, "Somente o administrador pode gerenciar as conexões compartilhadas."
        )


def service(request: Request):
    instance = getattr(request.app.state, "browser_connections", None)
    if instance is None:
        raise HTTPException(
            503, "Configure BROWSER_SESSION_KEY para habilitar as conexões."
        )
    return instance


class Input(BaseModel):
    model_config = {"extra": "forbid"}
    action: Literal[
        "click",
        "text",
        "key",
        "scroll",
        "home",
        "login",
        "move",
        "down",
        "up",
        "release",
    ]
    x: int = Field(default=0, ge=0, lt=1280)
    y: int = Field(default=0, ge=0, lt=800)
    text: SecretStr = Field(default=SecretStr(""), max_length=4096)
    key: SecretStr = Field(default=SecretStr("Tab"), min_length=1, max_length=80)
    button: Literal["left", "middle", "right"] = "left"
    click_count: int = Field(default=1, ge=1, le=3)
    modifiers: list[Literal["Shift", "Control", "Alt", "Meta"]] = Field(
        default_factory=list, max_length=4
    )
    delta: int = Field(default=0, ge=-1600, le=1600)
    delta_x: int = Field(default=0, ge=-1600, le=1600)


@router.get("", dependencies=[Depends(administrator)])
async def statuses(request: Request):
    return [await service(request).status(site) for site in SESSION_DOMAINS]


@router.post("/{site}/connect", dependencies=[Depends(administrator)])
async def connect(site: BrowserSourceId, request: Request):
    return await service(request).connect(site)


@router.post("/{site}/import", dependencies=[Depends(administrator)])
async def import_session(site: BrowserSourceId, value: SessionImport, request: Request):
    return await service(request).import_session(site, value.storage(site))


@router.get("/{site}/frame", dependencies=[Depends(administrator)])
async def frame(site: BrowserSourceId, request: Request):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        await service(request).frame(site), headers={"Cache-Control": "no-store"}
    )


@router.post("/{site}/local/start", dependencies=[Depends(administrator)])
async def start_local(site: BrowserSourceId, value: Agent, request: Request):
    return await service(request).start_local(site, value.agent_id)


@router.post("/{site}/local/next", dependencies=[Depends(administrator)])
async def next_local(site: BrowserSourceId, value: Agent, request: Request):
    return service(request).local.next(site, value.agent_id)


@router.post("/{site}/local/result", dependencies=[Depends(administrator)])
async def result_local(site: BrowserSourceId, value: Result, request: Request):
    instance = service(request)
    result = instance.local.complete(site, value)
    state = instance.read(site)
    if state.get("connection_method") == "local_extension":
        from panoptes_contracts.sources import captcha_page, login_page

        state["status"] = (
            "verification_required"
            if captcha_page(value.final_url, value.body.get_secret_value())
            else "reconnect_required"
            if value.blocked or login_page(value.final_url, value.body.get_secret_value())
            else "connected"
        )
        instance.write(site, state)
    return result


@router.post("/{site}/input", dependencies=[Depends(administrator)])
async def input_event(site: BrowserSourceId, value: Input, request: Request):
    return await service(request).input(site, value)


@router.post("/{site}/save", dependencies=[Depends(administrator)])
async def save(site: BrowserSourceId, request: Request):
    return await service(request).save(site)


@router.post("/{site}/cancel", dependencies=[Depends(administrator)])
async def cancel(site: BrowserSourceId, request: Request):
    return await service(request).cancel(site)


@router.delete("/{site}", dependencies=[Depends(administrator)])
async def disconnect(site: BrowserSourceId, request: Request):
    return await service(request).disconnect(site)


class Fetch(BaseModel):
    site: SourceId
    url: str = Field(max_length=2048)


@internal_router.post("/fetch", include_in_schema=False)
async def fetch(value: Fetch, request: Request):
    expected = os.getenv("BROWSER_SERVICE_TOKEN", "")
    supplied = request.headers.get("X-Browser-Service-Token", "")
    if not expected or not hmac.compare_digest(expected, supplied):
        raise HTTPException(403, "Acesso interno negado.")
    return await service(request).fetch(value.site, value.url)
