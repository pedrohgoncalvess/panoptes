"""Supported extraction sources and their explicit network boundaries."""

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from pydantic import model_validator

from .base import Contract

SourceId = Literal[
    "amazon_br", "mercado_livre_br", "kabum_br", "pichau_br", "terabyte_br"
]
BrowserSourceId = Literal["amazon_br", "mercado_livre_br", "pichau_br", "terabyte_br"]


class SourceSelection(Contract):
    contract_version: Literal["1.2"] = "1.2"
    sites: tuple[SourceId, ...] | Literal["all"] = "all"

    @model_validator(mode="after")
    def validate_sites(self):
        if self.sites != "all" and (
            not self.sites or len(set(self.sites)) != len(self.sites)
        ):
            raise ValueError("sites must be nonempty and unique")
        return self


@dataclass(frozen=True)
class SourceDefinition:
    id: SourceId
    name: str
    parser_slug: str
    page_hosts: tuple[str, ...]
    image_hosts: tuple[str, ...]
    key_pattern: str
    reason_prefix: str


SOURCES = {
    "amazon_br": SourceDefinition(
        "amazon_br",
        "Amazon Brasil",
        "amazon-product",
        ("www.amazon.com.br",),
        (
            "m.media-amazon.com",
            "images-na.ssl-images-amazon.com",
            "images-eu.ssl-images-amazon.com",
            "images-fe.ssl-images-amazon.com",
            "images.amazon.com",
            "ecx.images-amazon.com",
        ),
        r"[A-Z0-9]{10}",
        "amazon",
    ),
    "mercado_livre_br": SourceDefinition(
        "mercado_livre_br",
        "Mercado Livre",
        "mercado-livre-product",
        (
            "lista.mercadolivre.com.br",
            "www.mercadolivre.com.br",
            "produto.mercadolivre.com.br",
        ),
        ("http2.mlstatic.com", "http.mlstatic.com"),
        r"MLB\d{6,14}",
        "mercado_livre",
    ),
}

SOURCES.update(
    {
        "kabum_br": SourceDefinition(
            "kabum_br",
            "KaBuM!",
            "kabum-product",
            ("www.kabum.com.br", "kabum.com.br"),
            ("images.kabum.com.br",),
            r"\d{1,12}",
            "kabum",
        ),
        "pichau_br": SourceDefinition(
            "pichau_br",
            "Pichau",
            "pichau-product",
            ("www.pichau.com.br", "pichau.com.br"),
            ("media.pichau.com.br", "hotsite.pichau.com.br"),
            r"[a-z0-9]+(?:-[a-z0-9]+)*",
            "pichau",
        ),
        "terabyte_br": SourceDefinition(
            "terabyte_br",
            "TerabyteShop",
            "terabyte-product",
            ("www.terabyteshop.com.br", "terabyteshop.com.br"),
            ("img.terabyteshop.com.br",),
            r"\d{1,12}",
            "terabyte",
        ),
    }
)


def validate_source_key(site: SourceId, key: str):
    if not re.fullmatch(SOURCES[site].key_pattern, key):
        raise ValueError("invalid_source_key")


def login_page(url: str, html: str | bytes) -> bool:
    content = (
        html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    )
    if re.search(
        r"/(?:ap|login|auth|registration|account|account-verification)(?:/|$)|/central\.obj$",
        urlsplit(url).path,
        re.I,
    ):
        return True
    # Ignore script templates, but never send a real password form to capture storage.
    content = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>", " ", content, flags=re.I | re.S
    )
    return bool(re.search(r"<input\b[^>]*\btype\s*=\s*[\"']?password\b", content, re.I))


def captcha_page(url: str, html: str | bytes) -> bool:
    """Recognize challenge pages without treating ordinary CAPTCHA SDKs as blocks."""
    if re.search(r"/captcha(?:/|$)", urlsplit(url).path, re.I):
        return True
    content = (
        html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    )
    if (
        (urlsplit(url).hostname or "").endswith(".mercadolivre.com.br")
        and re.search(r'<button\b[^>]*\bid=["\']continue-button["\']', content, re.I)
        and re.search(r'\bclass=["\']micro-landing-button["\']', content, re.I)
        and "This page requires JavaScript to work" in content
    ):
        return True
    visible = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>", " ", content, flags=re.I | re.S
    )
    visible = " ".join(re.sub(r"<[^>]+>", " ", visible).lower().split())
    if re.search(
        r"<title[^>]*>\s*(?:just a moment|attention required|robot check)",
        content,
        re.I,
    ):
        return True
    return any(
        marker in visible
        for marker in (
            "por segurança, complete esta etapa",
            "por seguranca, complete esta etapa",
            "por seguridad, completa este paso",
            "enter the characters you see below",
            "sorry, we just need to make sure you're not a robot",
            "verifique que você é humano",
            "verify you are human",
            "checking your browser before accessing",
        )
    )
