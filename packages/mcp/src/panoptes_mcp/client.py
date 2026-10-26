"""Session-scoped API client. Credentials never become tool arguments or results."""

import json
import os
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from mcp.server.fastmcp.exceptions import ToolError


class PanoptesClient:
    @staticmethod
    def error(message, *, status=None, method="GET", response=None, code=None):
        retryable = (
            method == "GET"
            and code is None
            and (status is None or status in {429, 502, 503, 504})
        )
        details = {
            "code": code or (f"HTTP_{status}" if status else "API_UNAVAILABLE"),
            "message": message,
            "retryable": retryable,
            "outcome_unknown": method != "GET" and (status is None or status >= 500),
        }
        if details["outcome_unknown"]:
            details["recovery"] = "Consulte o estado salvo antes de repetir a escrita."
        if response is not None:
            try:
                details["correlation_id"] = str(
                    UUID(response.headers.get("X-Correlation-ID", ""))
                )
            except ValueError:
                pass
            retry = response.headers.get("Retry-After")
            if retry:
                try:
                    seconds = (
                        int(retry)
                        if retry.isdigit()
                        else int(
                            (
                                parsedate_to_datetime(retry) - datetime.now(UTC)
                            ).total_seconds()
                        )
                    )
                    details["retry_after_seconds"] = max(0, min(seconds, 86400))
                except (ValueError, TypeError, OverflowError):
                    pass
            if status == 422:
                try:
                    fields = response.json().get("fields", [])
                    if isinstance(fields, list):
                        details["invalid_fields"] = [
                            f
                            for f in fields
                            if isinstance(f, str)
                            and re.fullmatch(r"[a-z_][a-z_0-9.]{0,100}", f)
                        ][:30]
                except (ValueError, AttributeError):
                    pass
        return ToolError(json.dumps(details, ensure_ascii=False))

    def __init__(self, *, transport=None):
        url = os.getenv("PANOPTES_API_URL", "http://localhost:8000").rstrip("/")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("PANOPTES_API_URL must be an HTTP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("PANOPTES_API_URL must not contain credentials or query")
        if parsed.scheme == "http" and parsed.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
            "backend",
        }:
            raise ValueError("Use HTTPS for a remote Panoptes API")
        self.http = httpx.AsyncClient(
            base_url=url + "/", timeout=60, transport=transport, follow_redirects=False
        )
        self.token = os.getenv("PANOPTES_MCP_KEY")

    async def close(self):
        await self.http.aclose()

    async def request(self, method, path, *, params=None, body=None):
        try:
            if not self.token or not self.token.startswith("pmcp_"):
                raise ToolError(
                    "Configure PANOPTES_MCP_KEY com uma chave gerada em /mcp-keys."
                )
            token = self.token
            params = {
                k: self.serialize(v) for k, v in (params or {}).items() if v is not None
            }
            response = await self.http.request(
                method,
                path.lstrip("/"),
                params=params,
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
            if not response.is_success:
                # Never echo response bodies: they may contain scraped instructions,
                # credentials, internal SQL, or validation inputs.
                reasons = {
                    401: "Chave MCP expirada, revogada ou inválida. Gere uma nova chave.",
                    403: "Usuário sem permissão.",
                    404: "Registro não encontrado.",
                    409: "Conflito de configuração/fontes; releia o termo ou a rotina antes de alterar.",
                    422: "Parâmetros inválidos; consulte get_usage_guide(tool_name=...) e confira o schema, campos e fuso.",
                    429: "Limite temporário de requisições; aguarde retry_after_seconds antes de tentar novamente.",
                    503: "Serviço temporariamente indisponível; aguarde antes de consultar novamente.",
                }
                reason = reasons.get(
                    response.status_code,
                    "A API não concluiu a operação. Tente novamente.",
                )
                raise self.error(
                    f"Panoptes HTTP {response.status_code}: {reason}",
                    status=response.status_code,
                    method=method,
                    response=response,
                )
            try:
                return response.json() if response.content else {"ok": True}
            except ValueError:
                raise self.error(
                    "Resposta JSON inválida da API.",
                    method=method,
                    code="INVALID_RESPONSE",
                ) from None
        except httpx.HTTPError:
            raise self.error(
                "API Panoptes indisponível ou tempo limite excedido. "
                "Confira PANOPTES_API_URL e o backend.",
                method=method,
            ) from None

    @staticmethod
    def serialize(value):
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if isinstance(value, bool):
            return str(value).lower()
        return str(value)
