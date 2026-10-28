import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from panoptes_database.alerts import extraction_event
from panoptes_database.session import unit_of_work

from ..infrastructure.diagnostics import report_failure
from ..infrastructure.events import emit, failure_details, safe_details
from . import product_repository, queue_repository
from .service import (
    DiscoveryInterruptedError,
    PageBlockedError,
    PageUnavailableError,
    execute_request,
)


async def heartbeat(sessions, request_id, owner):
    while True:
        await asyncio.sleep(30)
        async with unit_of_work(sessions) as session:
            await queue_repository.renew(session, request_id, owner)


async def enqueue_available(sessions, browser=None):
    try:
        unavailable = await browser.unavailable_sites() if browser else ()
    except (httpx.HTTPError, ValueError):
        # Leave deadlines due until browser availability can be checked again.
        return
    async with unit_of_work(sessions) as session:
        await queue_repository.enqueue_due(session, unavailable)


async def schedule_loop(sessions, stop, browser=None):
    """Enqueue deadlines independently of long-running extractions."""
    while not stop.is_set():
        await enqueue_available(sessions, browser)
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except TimeoutError:
            pass


async def process(resources, request, owner):
    started = asyncio.get_running_loop().time()
    await emit(
        resources,
        request,
        "extraction_started",
        "Worker iniciou a extração.",
        mode=request["mode"],
        owner=str(owner),
    )
    site = None
    work = keepalive = None
    try:
        async with unit_of_work(resources.sessions) as session:
            context = await queue_repository.read_context(session, request)
            site = context.get("site", "amazon_br")
            routine, _ = await product_repository.register_runtime(session, site)
            context["runtime_routine_id"] = routine["public_id"]
        await emit(
            resources,
            request,
            "context_ready",
            "Fonte e critérios carregados.",
            site=site,
            mode=request["mode"],
            browser_configured=bool(resources.browser),
            max_pages=context.get("max_pages_qt"),
            max_candidates=context.get("max_candidates_qt"),
        )
        work = asyncio.create_task(execute_request(resources, request, context, owner))
        keepalive = asyncio.create_task(
            heartbeat(resources.sessions, request["id"], owner)
        )
        done, _ = await asyncio.wait(
            (work, keepalive), return_when=asyncio.FIRST_COMPLETED
        )
        if keepalive in done:
            await keepalive
        summary = await work
        statuses = [row["status"] for row in summary.get("products", [])]
        status = (
            "partial"
            if (
                any(value in ("failed", "uncertain") for value in statuses)
                or any(row.get("image_errors") for row in summary.get("products", []))
                or summary.get("truncated")
            )
            else "completed"
        )
        if request["mode"] == "refresh" and statuses and statuses[0] != "completed":
            status = "failed"
            product = summary["products"][0]
            summary = {
                **summary,
                "reason": product.get("reason") or product["status"],
                "product_status": product["status"],
            }
            if (
                product["status"] == "rejected"
                and product.get("reason") == "product_type_mismatch"
            ):
                summary["tracking_paused"] = True
    except DiscoveryInterruptedError as error:
        status = (
            "partial"
            if any(p["status"] == "completed" for p in error.products)
            else "failed"
        )
        summary = {**report_failure(error.cause, request), "products": error.products}
        await emit(
            resources,
            request,
            "extraction_interrupted",
            "Uma página posterior não pôde ser interpretada. Os resultados já obtidos foram preservados.",
            level="WARNING" if status == "partial" else "ERROR",
            site=site,
            **failure_details(error.cause),
        )
    except PageBlockedError as error:
        await emit(
            resources,
            request,
            "extraction_blocked",
            "Extração interrompida por bloqueio ou verificação do site.",
            level="ERROR",
            site=site,
            reason=error.reason,
            **{k: v for k, v in error.details.items() if k not in ("site", "products")},
        )
        status, summary = "blocked", {"reason": error.reason, **error.details}
    except PageUnavailableError as error:
        await emit(
            resources,
            request,
            "extraction_unavailable",
            "Fonte indisponível após as tentativas.",
            level="ERROR",
            site=site,
            reason=error.reason,
            **{k: v for k, v in error.details.items() if k not in ("site", "products")},
        )
        status = (
            "partial"
            if any(
                row["status"] == "completed"
                for row in error.details.get("products", [])
            )
            else "failed"
        )
        summary = {"reason": error.reason, **error.details}
    except queue_repository.LeaseLostError:
        await emit(
            resources,
            request,
            "lease_lost",
            "Worker perdeu a reserva desta execução; outro worker poderá retomá-la.",
            level="WARNING",
            site=site,
        )
        return
    except Exception as error:
        await emit(
            resources,
            request,
            "extraction_failed",
            "A extração falhou durante o processamento.",
            level="ERROR",
            site=site,
            **failure_details(error),
        )
        status, summary = "failed", report_failure(error, request)
    finally:
        for task in (work, keepalive):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (work, keepalive) if task is not None),
            return_exceptions=True,
        )
    async with unit_of_work(resources.sessions) as session:
        try:
            await queue_repository.finish(
                session, request["id"], owner, status, summary
            )
            await extraction_event(
                session, request, "extraction_finished", status=status
            )
            if status in ("failed", "blocked", "partial"):
                await extraction_event(
                    session, request, "extraction_error", status=status
                )
        except queue_repository.LeaseLostError:
            await emit(
                resources,
                request,
                "lease_lost",
                "Resultado não gravado: a reserva da execução expirou.",
                level="WARNING",
                site=site,
            )
            return
    if summary.get("tracking_paused"):
        await emit(
            resources,
            request,
            "tracking_paused",
            "Acompanhamento suspenso: o tipo do produto não corresponde à busca.",
            level="WARNING",
            site=site,
            reason=summary["reason"],
        )
    await emit(
        resources,
        request,
        "extraction_finished",
        "Execução finalizada.",
        site=site,
        level="ERROR"
        if status == "failed"
        else "WARNING"
        if status in ("blocked", "partial")
        else "INFO",
        status=status,
        duration_ms=round((asyncio.get_running_loop().time() - started) * 1000),
        products=len(summary.get("products", [])),
        reason=summary.get("reason"),
        product_status=summary.get("product_status"),
        error=summary.get("error"),
    )
    print(
        json.dumps(
            {
                "event": "scrape_finished",
                "request_id": str(request["public_id"]),
                "correlation_id": str(request["correlation_id"]),
                "status": status,
                "summary": safe_details(summary),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ),
        flush=True,
    )


async def run(resources, stop, *, once=False):
    owner = uuid4()
    while not stop.is_set():
        await enqueue_available(resources.sessions, resources.browser)
        async with unit_of_work(resources.sessions) as session:
            request = await queue_repository.claim(session, owner)
            if request:
                await extraction_event(
                    session, request, "extraction_started", status="running"
                )
        if request:
            await process(resources, request, owner)
        elif once:
            return
        else:
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                pass
        if once:
            return
