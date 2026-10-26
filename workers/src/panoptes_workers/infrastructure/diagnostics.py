"""Structured failure logs without SQL parameters, HTTP credentials or local values."""

import json
import traceback
from datetime import datetime, timezone
from uuid import uuid4

from .events import failure_details


def report_failure(error, request, *, source_key=None):
    details = {**failure_details(error), "error_id": str(uuid4())}
    sqlstate = getattr(getattr(error, "orig", None), "sqlstate", None)
    if sqlstate:
        details["sqlstate"] = sqlstate
    print(
        json.dumps(
            {
                "event": "scrape_error",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "request_id": str(request["public_id"]),
                "correlation_id": str(request["correlation_id"]),
                "source_key": source_key,
                **details,
                "stack": [
                    {
                        "file": frame.filename,
                        "line": frame.lineno,
                        "function": frame.name,
                    }
                    for frame in traceback.extract_tb(error.__traceback__)
                ],
            }
        ),
        flush=True,
    )
    return details
