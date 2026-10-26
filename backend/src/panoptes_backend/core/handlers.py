import json
import logging
import re
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .errors import DomainError


def install_handlers(app):
    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return response(request, error.status_code, str(error), error.code)

    @app.middleware("http")
    async def correlation(request: Request, call_next):
        request.state.correlation_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        return response

    def response(request, status, detail, code, headers=None, fields=None):
        return JSONResponse(
            status_code=status,
            content={
                "detail": detail,
                "code": code,
                "correlation_id": request.state.correlation_id,
                **({"fields": fields} if fields is not None else {}),
            },
            headers=headers,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return response(
            request, error.status_code, error.detail, "HTTP_ERROR", error.headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        fields = sorted(
            {
                ".".join(
                    str(part)
                    for part in item["loc"]
                    if part not in {"body", "query", "path"}
                )
                for item in error.errors()
            }
        )
        fields = [
            field for field in fields if re.fullmatch(r"[a-z_][a-z_0-9.]{0,100}", field)
        ][:30]
        return response(
            request, 422, "Invalid request", "VALIDATION_ERROR", fields=fields
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        correlation_id = getattr(request.state, "correlation_id", str(uuid4()))
        logging.getLogger("panoptes").error(
            json.dumps(
                {
                    "level": "ERROR",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "domain": "backend",
                    "event": "unhandled_error",
                    "correlation_id": correlation_id,
                    "type": type(error).__name__,
                }
            )
        )
        return response(
            request,
            500,
            "Internal server error",
            "INTERNAL_ERROR",
            {"X-Correlation-ID": correlation_id},
        )
