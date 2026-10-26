"""Bounded, secret-safe session imports from the browser extension."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr

SESSION_DOMAINS = {
    "pichau_br": ("pichau.com.br",),
    "terabyte_br": ("terabyteshop.com.br",),
    "amazon_br": ("amazon.com.br", "amazon.com"),
    "mercado_livre_br": (
        "mercadolivre.com.br",
        "mercadolivre.com",
        "mercadolibre.com",
        "mercadopago.com.br",
    ),
}


def allowed_host(host, site):
    return any(
        host == domain or host.endswith("." + domain)
        for domain in SESSION_DOMAINS[site]
    )


class StrictModel(BaseModel):
    model_config = {"extra": "forbid"}


class Cookie(StrictModel):
    name: str = Field(min_length=1, max_length=256)
    value: SecretStr = Field(max_length=16384)
    domain: str = Field(min_length=1, max_length=253)
    path: str = Field(default="/", max_length=2048, pattern=r"^/")
    expires: float = Field(default=-1, ge=-1, allow_inf_nan=False)
    httpOnly: bool = False
    secure: bool = True
    sameSite: Literal["Strict", "Lax", "None"] = "Lax"


class StorageItem(StrictModel):
    name: str = Field(max_length=1024)
    value: SecretStr = Field(max_length=65536)


class Origin(StrictModel):
    origin: str = Field(max_length=2048)
    localStorage: list[StorageItem] = Field(default_factory=list, max_length=1000)
    sessionStorage: list[StorageItem] = Field(default_factory=list, max_length=1000)


class SessionImport(StrictModel):
    cookies: list[Cookie] = Field(min_length=1, max_length=1000)
    origins: list[Origin] = Field(default_factory=list, max_length=10)

    def storage(self, site):
        from fastapi import HTTPException

        for cookie in self.cookies:
            host = cookie.domain.removeprefix(".")
            if not allowed_host(host, site):
                raise HTTPException(422, "Cookie fora dos domínios permitidos.")
        for origin in self.origins:
            try:
                parts = urlsplit(origin.origin)
                port = parts.port
            except ValueError:
                raise HTTPException(422, "Origem de armazenamento inválida.") from None
            if (
                parts.scheme != "https"
                or not allowed_host(parts.hostname or "", site)
                or port not in (None, 443)
                or parts.username
                or parts.password
                or parts.path
                or parts.query
                or parts.fragment
            ):
                raise HTTPException(422, "Origem de armazenamento inválida.")
        state = {
            "cookies": [
                dict(c.model_dump(), value=c.value.get_secret_value())
                for c in self.cookies
            ],
            "origins": [
                {
                    "origin": o.origin,
                    "localStorage": [
                        dict(i.model_dump(), value=i.value.get_secret_value())
                        for i in o.localStorage
                    ],
                    **(
                        {
                            "sessionStorage": [
                                dict(i.model_dump(), value=i.value.get_secret_value())
                                for i in o.sessionStorage
                            ]
                        }
                        if o.sessionStorage
                        else {}
                    ),
                }
                for o in self.origins
            ],
        }
        import json

        if len(json.dumps(state).encode()) > 1024 * 1024:
            raise HTTPException(413, "A sessão excede o limite de 1 MB.")
        return state
