import asyncio
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from panoptes_contracts import (
    Evidence,
    ExtractionJob,
    ExtractionPolicy,
    Layer,
    LayerOutcome,
)
from panoptes_contracts.discovery import ProductMatchCriteria
from panoptes_contracts.pipeline import run_pipeline
from panoptes_database.session import unit_of_work

from ..infrastructure.diagnostics import report_failure
from ..infrastructure.events import emit, failure_details
from ..infrastructure.http import block_reason, download
from ..sources import get_source, source_for_url
from . import capture_repository, product_repository, queue_repository
from .captures import capture_image, capture_page


class PageBlockedError(Exception):
    def __init__(self, details):
        super().__init__("amazon_blocked")
        self.details = details
        self.reason = f"{details.get('reason_prefix', 'amazon')}_blocked"


class PageUnavailableError(Exception):
    def __init__(self, details):
        super().__init__("amazon_unavailable")
        self.details = details
        self.reason = f"{details.get('reason_prefix', 'amazon')}_unavailable"


class DiscoveryInterruptedError(Exception):
    def __init__(self, cause, products):
        super().__init__("discovery_interrupted")
        self.cause = cause
        self.products = products


@dataclass(frozen=True)
class WorkflowResources:
    sessions: object
    storage: object
    bucket: str
    http: object
    throttle: asyncio.Lock
    interval: float
    browser: object = None
    events: object = None
    commerce: object = None
    classifier: object = None


async def parse_capture(
    resources, request, source, stage, page, snapshot, asset, parser, *args
):
    """Keep the exact S3 capture linked to any failed parser invocation."""
    try:
        return await asyncio.to_thread(
            parser, page.body.decode(page.encoding, errors="replace"), *args
        )
    except Exception as error:
        await emit(
            resources,
            request,
            "parser_failed",
            "O leitor não conseguiu interpretar a página. O HTML foi preservado no S3 para análise.",
            level="ERROR",
            site=source.definition.id,
            stage=stage,
            parser=source.definition.parser_slug,
            parser_version=source.parser_version,
            snapshot_id=str(snapshot.public_id),
            asset_id=str(asset["public_id"]),
            sha256=snapshot.sha256,
            bytes=len(page.body),
            http_status=page.status,
            capture_mode=page.capture_mode,
            source_url=page.source_url,
            final_url=page.final_url,
            captured_at=snapshot.captured_at.isoformat(),
            **failure_details(error),
        )
        raise


async def fetch_page(resources, request, owner, url):
    source = source_for_url(url)
    for attempt in range(1, 4):
        await emit(
            resources,
            request,
            "page_fetch_started",
            "Iniciando leitura da página.",
            site=source.definition.id,
            source_url=url,
            attempt=attempt,
            browser_configured=bool(resources.browser),
        )
        page = None
        if resources.browser:
            page = await resources.browser.fetch(
                source.definition.id, url, resources.throttle, resources.interval
            )
            if isinstance(page, dict):
                await emit(
                    resources,
                    request,
                    "page_blocked",
                    "O navegador conectado interrompeu a leitura.",
                    level="WARNING",
                    site=source.definition.id,
                    cause=page.get("cause", page["blocked"]),
                    source_url=url,
                    attempt=attempt,
                )
                raise PageBlockedError(
                    {
                        "site": source.definition.id,
                        "reason_prefix": source.definition.reason_prefix,
                        "cause": page.get("cause", page["blocked"]),
                        "source_url": url,
                        "attempt": attempt,
                    }
                )
        if page is None:
            await emit(
                resources,
                request,
                "http_fallback",
                "Usando leitura HTTP: não há sessão de navegador disponível para esta fonte.",
                level="WARNING",
                site=source.definition.id,
                source_url=url,
            )
            page = await download(
                resources.http,
                resources.throttle,
                url,
                resources.interval,
                allowed_hosts=source.definition.page_hosts,
            )
        capture = await capture_page(
            resources.sessions,
            resources.storage,
            resources.bucket,
            request,
            owner,
            page,
        )
        reason = block_reason(page)
        await emit(
            resources,
            request,
            "source_page_fetched",
            "Página recebida e captura armazenada.",
            site=source.definition.id,
            http_status=page.status,
            capture_mode=page.capture_mode,
            bytes=len(page.body),
            media_type=page.media_type,
            source_url=page.source_url,
            final_url=page.final_url,
            attempt=attempt,
            snapshot_id=str(capture[0].public_id),
            asset_id=str(capture[2]["public_id"]),
        )
        details = {
            "site": source.definition.id,
            "reason_prefix": source.definition.reason_prefix,
            "cause": reason or f"http_status_{page.status}",
            "http_status": page.status,
            "source_url": page.source_url,
            "final_url": page.final_url,
            "snapshot_id": str(capture[0].public_id),
            "asset_id": str(capture[2]["public_id"]),
            "attempt": attempt,
        }
        if reason:
            await emit(
                resources,
                request,
                "page_blocked",
                "O site exigiu verificação ou recusou o acesso.",
                level="WARNING",
                site=source.definition.id,
                **{k: v for k, v in details.items() if k != "site"},
            )
            raise PageBlockedError(details)
        if page.status not in (500, 502, 503, 504):
            break
        if attempt == 3:
            raise PageUnavailableError(details)
        await emit(
            resources,
            request,
            "page_retry",
            "A fonte está indisponível. Uma nova tentativa será feita.",
            level="WARNING",
            site=source.definition.id,
            http_status=page.status,
            attempt=attempt,
            delay_seconds=2**attempt,
        )
        await asyncio.sleep(2**attempt)
    if page.status != 200:
        raise ValueError(f"http_status_{page.status}")
    if page.media_type not in ("text/html", "application/xhtml+xml"):
        raise ValueError("unexpected_content_type")
    return page, capture


async def extract_product(resources, request, context, owner, candidate, criteria):
    source = get_source(context.get("site", "amazon_br"))
    from sqlalchemy import text

    async with unit_of_work(resources.sessions) as session:
        excluded = (
            await session.execute(
                text("""SELECT 1 FROM scraping.excluded_page
          WHERE site=:site AND source_key=:key"""),
                {"site": source.definition.id, "key": candidate.source_key},
            )
        ).scalar_one_or_none()
    if excluded:
        return {"source_key": candidate.source_key, "status": "excluded"}
    await emit(
        resources,
        request,
        "product_started",
        "Iniciando extração do produto.",
        site=source.definition.id,
        source_key=candidate.source_key,
    )
    page, (snapshot, snapshot_id, html_asset) = await fetch_page(
        resources, request, owner, str(candidate.url)
    )
    await emit(
        resources,
        request,
        "product_parse_started",
        "Interpretando página do produto.",
        site=source.definition.id,
        parser=source.definition.parser_slug,
        source_key=candidate.source_key,
    )
    detail = await parse_capture(
        resources,
        request,
        source,
        "product",
        page,
        snapshot,
        html_asset,
        source.parse_product,
        page.final_url,
        candidate.source_key,
        criteria.category,
    )
    await emit(
        resources,
        request,
        "product_parsed",
        "Dados do produto interpretados.",
        site=source.definition.id,
        source_key=candidate.source_key,
        parser=source.definition.parser_slug,
    )
    final_candidate = candidate.model_copy(
        update={"title": detail.entity.title, "authors": detail.authors}
    )
    from panoptes_contracts.discovery import TrackedCandidate

    if isinstance(final_candidate, TrackedCandidate):
        final_candidate = final_candidate.model_copy(
            update={"snapshot_id": snapshot.public_id}
        )
    if criteria.match_mode == "intent":
        from ..common.intent import qualify_intent

        if resources.classifier:
            validation = await resources.classifier.classify(
                final_candidate,
                criteria,
                detail,
                context={
                    "scrape_request_id": request["id"],
                    "html_snapshot_id": snapshot_id,
                    "site": source.definition.id,
                    "source_key": candidate.source_key,
                },
            )
        else:
            validation = qualify_intent(final_candidate, criteria, detail=detail)
        await emit(
            resources,
            request,
            "product_classified",
            "Produto comparado à busca e à descrição usando os dados da página.",
            level="WARNING" if validation.decision == "uncertain" else "INFO",
            site=source.definition.id,
            source_key=candidate.source_key,
            decision=validation.decision,
            reason=validation.reason,
            classifier=validation.validator_version,
        )
    elif criteria.match_mode == "profile":
        from ..common.qualification import qualify

        validation = qualify(final_candidate, criteria, detail=detail)
    else:
        validation = source.validate(
            final_candidate,
            criteria,
            detail=True,
            isbn=detail.isbn,
            catalog=detail.catalog,
        )
    async with unit_of_work(resources.sessions) as session:
        await queue_repository.guard(session, request["id"], owner)
        await capture_repository.save_detail_validation(
            session, request["id"], candidate.source_key, validation, snapshot_id
        )
    if validation.decision != "accepted":
        await emit(
            resources,
            request,
            "product_validation",
            "Produto não aceito pelos critérios da extração.",
            level="WARNING",
            site=source.definition.id,
            source_key=candidate.source_key,
            decision=validation.decision,
            reason=validation.reason,
        )
        return {
            "source_key": candidate.source_key,
            "status": validation.decision,
            "reason": validation.reason,
        }
    from ..common.commerce import extract_commerce

    detail, unresolved = await asyncio.to_thread(
        extract_commerce,
        detail,
        page.body.decode(page.encoding, errors="replace"),
        source.definition.id,
    )
    if resources.commerce:
        detail = await resources.commerce.enrich(
            detail,
            unresolved,
            context={
                "scrape_request_id": request["id"],
                "html_snapshot_id": snapshot_id,
                "snapshot_public_id": str(snapshot.public_id),
                "site": source.definition.id,
                "source_key": candidate.source_key,
            },
        )
    report = detail.offer.commercial_extraction
    if report:
        await emit(
            resources,
            request,
            "commercial_extracted",
            "Preços, pagamentos e condições comerciais estruturados e vinculados ao histórico.",
            source_key=candidate.source_key,
            site=source.definition.id,
            payment_count=len(detail.offer.payment_options),
            promotion_count=len(detail.offer.promotions),
            shipping_count=len(detail.offer.shipping_options),
            fallback_status=report.fallback_status,
            model=report.model,
            unresolved_count=len(report.unresolved),
        )
    evidence = tuple(
        Evidence(
            entity_source_key=candidate.source_key,
            snapshot_id=snapshot.public_id,
            field=field,
            locator=locator,
            method=method,
            excerpt=excerpt,
        )
        for field, locator, method, excerpt in (
            ("source_key", "capture.final_url", "text", candidate.source_key),
            ("url", "capture.final_url", "text", str(detail.entity.url)),
            ("title", source.title_locator, "css", detail.entity.title),
        )
    )
    job = ExtractionJob(
        public_id=uuid4(),
        correlation_id=request["correlation_id"],
        routine_id=context["runtime_routine_id"],
        routine_version="1.0.0",
        snapshot=snapshot,
        parser_slug=source.definition.parser_slug,
        parser_version=source.parser_version,
        policy=ExtractionPolicy(layers=(Layer.SITE_PARSER,)),
        idempotency_key=f"{request['public_id']}:{candidate.source_key}:{snapshot.public_id}",
    )

    async def parser(_):
        return LayerOutcome(
            status="success",
            entities=(detail.entity,),
            evidence=evidence,
            confidence=Decimal(1),
        )

    result = await run_pipeline(job, {Layer.SITE_PARSER: parser})
    assets = [html_asset]
    image_errors = []
    for url in detail.offer.image_urls:
        try:
            image = await download(
                resources.http,
                resources.throttle,
                str(url),
                resources.interval,
                image=True,
                allowed_hosts=source.definition.image_hosts,
            )
            assets.append(
                await capture_image(
                    resources.sessions,
                    resources.storage,
                    resources.bucket,
                    request,
                    owner,
                    image,
                )
            )
        except queue_repository.LeaseLostError:
            raise
        except Exception as error:
            await emit(
                resources,
                request,
                "image_failed",
                "Falha na leitura ou no armazenamento de uma imagem.",
                level="WARNING",
                site=source.definition.id,
                source_key=candidate.source_key,
                source_url=str(url),
                **failure_details(error),
            )
            image_errors.append({"url": str(url), "error": type(error).__name__})
    async with unit_of_work(resources.sessions) as session:
        await queue_repository.guard(session, request["id"], owner)
        job_id = await product_repository.save_job(
            session, request, job, snapshot_id, result
        )
        if result.status == "completed":
            await product_repository.save_product(
                session, request, context, detail, job_id, result, assets
            )
    await emit(
        resources,
        request,
        "product_saved",
        "Processamento do produto concluído.",
        site=source.definition.id,
        source_key=candidate.source_key,
        status=result.status,
        assets=len(assets),
        image_errors=len(image_errors),
    )
    return {
        "source_key": candidate.source_key,
        "status": result.status,
        "image_errors": image_errors,
    }


async def discover(resources, request, context, owner):
    source = get_source(context.get("site", "amazon_br"))
    criteria = ProductMatchCriteria.model_validate(context["criteria"])
    next_url = source.search_url(
        context["term"],
        book_only=criteria.category == "book"
        or bool(criteria.authors or criteria.isbn),
    )
    seen, outcomes = set(), []
    pagination_incomplete = False
    async with unit_of_work(resources.sessions) as session:
        observed = await capture_repository.observed_keys(session, request["id"])
    for page_qt in range(1, context["max_pages_qt"] + 1):
        if not next_url:
            break
        await emit(
            resources,
            request,
            "search_page_started",
            "Iniciando página de resultados da busca.",
            site=source.definition.id,
            page=page_qt,
            source_url=next_url,
        )
        try:
            page, (snapshot, snapshot_id, search_asset) = await fetch_page(
                resources, request, owner, next_url
            )
        except (PageUnavailableError, PageBlockedError) as error:
            error.details["products"] = outcomes
            raise
        await emit(
            resources,
            request,
            "search_parse_started",
            "Interpretando resultados da busca.",
            site=source.definition.id,
            page=page_qt,
            parser=source.definition.parser_slug,
        )
        try:
            candidates, next_url = await parse_capture(
                resources,
                request,
                source,
                "search",
                page,
                snapshot,
                search_asset,
                source.parse_search,
                snapshot.public_id,
                page_qt,
            )
        except Exception as error:
            if outcomes:
                raise DiscoveryInterruptedError(error, outcomes) from error
            raise
        if source.pagination_unavailable and await asyncio.to_thread(
            source.pagination_unavailable,
            page.body.decode(page.encoding, errors="replace"),
        ):
            pagination_incomplete = True
            await emit(
                resources,
                request,
                "pagination_unavailable",
                "A próxima página não informou uma URL válida. Os resultados desta página serão preservados.",
                level="WARNING",
                site=source.definition.id,
                page=page_qt,
                reason="pagination_url_unavailable",
                source_url=page.source_url,
            )
        await emit(
            resources,
            request,
            "search_parsed",
            "Resultados da busca interpretados.",
            site=source.definition.id,
            page=page_qt,
            candidates=len(candidates),
            has_next_page=bool(next_url),
        )
        for candidate in candidates:
            if candidate.source_key in seen:
                continue
            seen.add(candidate.source_key)
            validation = source.validate(candidate, criteria)
            async with unit_of_work(resources.sessions) as session:
                await queue_repository.guard(session, request["id"], owner)
                await capture_repository.save_candidate(
                    session, request["id"], snapshot_id, validation
                )
            if validation.decision != "accepted":
                await emit(
                    resources,
                    request,
                    "candidate_validation",
                    "Candidato não aceito pelos critérios da busca.",
                    site=source.definition.id,
                    source_key=candidate.source_key,
                    decision=validation.decision,
                    reason=validation.reason,
                )
                outcomes.append(
                    {"source_key": candidate.source_key, "status": validation.decision}
                )
            elif candidate.source_key in observed:
                outcomes.append(
                    {
                        "source_key": candidate.source_key,
                        "status": "completed",
                        "recovered": True,
                    }
                )
            else:
                try:
                    outcomes.append(
                        await extract_product(
                            resources, request, context, owner, candidate, criteria
                        )
                    )
                except PageBlockedError as error:
                    error.details["products"] = outcomes
                    raise
                except queue_repository.LeaseLostError:
                    raise
                except PageUnavailableError as error:
                    await emit(
                        resources,
                        request,
                        "product_failed",
                        "Produto indisponível após as tentativas.",
                        level="ERROR",
                        site=source.definition.id,
                        source_key=candidate.source_key,
                        reason=error.reason,
                    )
                    outcomes.append(
                        {
                            "source_key": candidate.source_key,
                            "status": "failed",
                            "reason": error.reason,
                            **error.details,
                        }
                    )
                except Exception as error:
                    await emit(
                        resources,
                        request,
                        "product_failed",
                        "Não foi possível concluir a extração do produto.",
                        level="ERROR",
                        site=source.definition.id,
                        source_key=candidate.source_key,
                        **failure_details(error),
                    )
                    outcomes.append(
                        {
                            "source_key": candidate.source_key,
                            "status": "failed",
                            **report_failure(
                                error, request, source_key=candidate.source_key
                            ),
                        }
                    )
            if len(seen) >= context.get("max_candidates_qt", 100):
                return {"products": outcomes, "truncated": True}
    return {
        "products": outcomes,
        "truncated": pagination_incomplete,
        **({"reason": "pagination_url_unavailable"} if pagination_incomplete else {}),
    }


async def execute_request(resources, request, context, owner):
    if request["mode"] == "discover":
        return await discover(resources, request, context, owner)
    from panoptes_contracts.discovery import TrackedCandidate

    candidate = TrackedCandidate(
        site=context.get("site", "amazon_br"),
        source_key=context["source_key"],
        url=context["product_url"],
        title=context.get("title")
        or context["criteria"].get("title")
        or context["source_key"],
    )
    criteria = ProductMatchCriteria.model_validate(context["criteria"])
    async with unit_of_work(resources.sessions) as session:
        observed = await capture_repository.observed_keys(session, request["id"])
    if context["source_key"] in observed:
        return {
            "products": [
                {
                    "source_key": context["source_key"],
                    "status": "completed",
                    "recovered": True,
                }
            ]
        }
    return {
        "products": [
            await extract_product(
                resources, request, context, owner, candidate, criteria
            )
        ]
    }
