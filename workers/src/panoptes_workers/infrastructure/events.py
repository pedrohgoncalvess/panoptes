"""Persist bounded execution diagnostics without exception text or credentials."""

import json
import re
import traceback
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from panoptes_database.session import unit_of_work
from sqlalchemy import text


def safe_details(value, depth=0):
    if depth > 5:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            str(key): safe_details(item, depth + 1)
            for key, item in list(value.items())[:50]
            if not re.search(
                r"cookie|authorization|password|senha|token|secret|body|html|header",
                str(key),
                re.I,
            )
        }
    if isinstance(value, (list, tuple)):
        return [safe_details(item, depth + 1) for item in value[:30]]
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            parts = urlsplit(value)
            return urlunsplit((parts.scheme, parts.hostname or "", parts.path, "", ""))[
                :2000
            ]
        return value[:2000]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:200]


def failure_details(error):
    details = {"error": type(error).__name__}
    # Only short machine-readable application codes may be exported. Arbitrary
    # exception strings can include SQL parameters, HTML or credentials.
    if isinstance(error, ValueError) and re.fullmatch(
        r"[a-z][a-z0-9_]{2,100}", str(error)
    ):
        details["reason"] = str(error)
    response = getattr(error, "response", None)
    if response is not None:
        details["http_status"] = response.status_code
    sqlstate = getattr(getattr(error, "orig", None), "sqlstate", None)
    if sqlstate:
        details["sqlstate"] = sqlstate
    details["stack"] = [
        {
            "file": frame.filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
            "line": frame.lineno,
            "function": frame.name,
        }
        for frame in traceback.extract_tb(error.__traceback__)[-15:]
    ]
    return details


class DatabaseEvents:
    def __init__(self, sessions):
        self.sessions = sessions

    async def write(self, request, event):
        async with unit_of_work(self.sessions) as session:
            # Serialize allocation+commit so SSE never skips a late-committing
            # lower sequence number when several worker replicas write events.
            await session.execute(text("SELECT pg_advisory_xact_lock(710052026)"))
            await session.execute(
                text("""
                INSERT INTO scraping.extraction_log
                  (request_id,correlation_id,site,level,event,message,details)
                VALUES (:request_id,:correlation_id,:site,:level,:event,:message,CAST(:details AS jsonb))
            """),
                {
                    "request_id": request["id"],
                    "correlation_id": request["correlation_id"],
                    "site": event.get("site"),
                    "level": event["level"],
                    "event": event["event"],
                    "message": event["message"],
                    "details": json.dumps(event["details"]),
                },
            )


async def emit(
    resources, request, event, message, *, level="INFO", site=None, **details
):
    entry = {
        "event": event,
        "message": message,
        "level": level,
        "site": site,
        "request_id": str(request["public_id"]),
        "correlation_id": str(request["correlation_id"]),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": safe_details(details),
    }
    print(json.dumps(entry, ensure_ascii=False), flush=True)
    sink = getattr(resources, "events", None)
    if sink is not None:
        try:
            await sink.write(request, entry)
        except Exception as error:
            # Recording diagnostics must not undo an extraction or its lease.
            print(
                json.dumps(
                    {
                        "event": "log_persistence_failed",
                        "request_id": entry["request_id"],
                        "error": type(error).__name__,
                    }
                ),
                flush=True,
            )
