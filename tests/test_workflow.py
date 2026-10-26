import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from panoptes_workers.workflow import (
    capture_repository,
    product_repository,
    queue_repository,
)
from panoptes_workers.workflow.service import (
    PageBlockedError,
    PageUnavailableError,
    WorkflowResources,
    execute_request,
    fetch_page,
)

FIXTURES = Path(__file__).resolve().parents[1] / "workers/parsers/amazon-book"


@pytest.mark.parametrize(
    "site,fixture",
    [
        ("kabum_br", "gpu-in-stock"),
        ("pichau_br", "gpu"),
        ("pichau_br", "upgrade-kit"),
        ("terabyte_br", "ssd"),
    ],
)
async def test_hardware_refresh_uses_registered_adapter_and_saves_observation(
    boundaries, site, fixture
):
    from panoptes_contracts.offers import ProductDetail
    from panoptes_workers.sources import get_source

    source = get_source(site)
    folder = FIXTURES.parent / source.definition.parser_slug
    expected = ProductDetail.model_validate_json(
        (folder / f"{fixture}.expected.json").read_text(encoding="utf-8")
    )
    product_html = (folder / f"{fixture}.html").read_bytes()

    def response(request):
        if request.url.host in source.definition.image_hosts:
            return httpx.Response(
                200,
                content=b"\x89PNG\r\n\x1a\nfixture",
                headers={"content-type": "image/png"},
            )
        return httpx.Response(
            200,
            content=product_html,
            headers={"content-type": "text/html; charset=utf-8"},
        )

    request, context = request_context("refresh")
    context.update(
        site=site,
        source_key=expected.entity.source_key,
        product_url=str(expected.entity.url),
        criteria={
            "title": expected.entity.title
            if fixture == "upgrade-kit"
            else "ssd kingston nv3 500gb"
            if site == "terabyte_br"
            else "rtx 3070"
        },
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        resources = WorkflowResources(
            boundaries, AsyncMock(), "panoptes", client, asyncio.Lock(), 0
        )
        summary = await execute_request(resources, request, context, uuid4())
    assert summary["products"][0]["status"] == "completed"
    product_repository.save_product.assert_awaited_once()
    product_repository.save_job.assert_awaited_once()
    if fixture == "upgrade-kit":
        persisted = product_repository.save_product.await_args.args[3]
        assert persisted.offer.price == expected.offer.price
        assert persisted.offer.list_price == expected.offer.list_price
        assert persisted.offer.availability == "out_of_stock"
        assert persisted.entity.price == expected.entity.price


@pytest.fixture
def boundaries(monkeypatch):
    for name in ("save_snapshot", "save_candidate", "save_detail_validation"):
        monkeypatch.setattr(capture_repository, name, AsyncMock(return_value=1))
    monkeypatch.setattr(
        capture_repository, "observed_keys", AsyncMock(return_value=set())
    )

    async def asset(_, value):
        return {"id": 1, "public_id": value.public_id}

    monkeypatch.setattr(capture_repository, "save_asset", AsyncMock(side_effect=asset))
    monkeypatch.setattr(queue_repository, "guard", AsyncMock())
    monkeypatch.setattr(product_repository, "save_job", AsyncMock(return_value=1))
    monkeypatch.setattr(product_repository, "save_product", AsyncMock())
    sessions = MagicMock()
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock())
    session.execute.return_value.scalar_one_or_none.return_value = None
    sessions.return_value.__aenter__ = AsyncMock(return_value=session)
    sessions.return_value.__aexit__ = AsyncMock(return_value=False)
    return sessions


def request_context(mode="discover"):
    request = {"id": 1, "public_id": uuid4(), "correlation_id": uuid4(), "mode": mode}
    context = {
        "id": 1,
        "term": "Database Internals",
        "criteria": {"title": "Database Internals", "authors": ["Alex Petrov"]},
        "max_pages_qt": 1,
        "refresh_interval_seconds": 86400,
        "runtime_routine_id": uuid4(),
        "source_key": "1492040347",
        "product_url": "https://www.amazon.com.br/dp/1492040347",
    }
    return request, context


@pytest.mark.parametrize("decision", ["accepted", "rejected", "uncertain"])
async def test_mapping_classifies_parsed_product_before_persistence(
    boundaries, decision
):
    from decimal import Decimal

    from panoptes_contracts.discovery import CandidateValidation

    visited = []

    def response(request):
        visited.append(str(request.url))
        if request.url.path == "/s":
            data = (FIXTURES / "search.html").read_bytes()
        elif request.url.host == "m.media-amazon.com":
            return httpx.Response(
                200,
                content=b"\x89PNG\r\n\x1a\nfixture",
                headers={"content-type": "image/png"},
            )
        else:
            data = (FIXTURES / "product.html").read_bytes()
        return httpx.Response(200, content=data, headers={"content-type": "text/html"})

    async def classify(candidate, criteria, detail, *, context):
        assert detail.offer.price is not None
        assert detail.entity.title == candidate.title
        assert criteria.description == "edição impressa"
        assert context["html_snapshot_id"] == 1
        return CandidateValidation(
            candidate=candidate,
            decision=decision,
            reason="intent_classified",
            confidence=Decimal("0.95"),
        )

    request, context = request_context()
    context.update(
        term="Database Internals",
        max_candidates_qt=1,
        criteria={
            "match_mode": "intent",
            "query": "Database Internals",
            "description": "edição impressa",
        },
    )
    classifier = MagicMock(classify=AsyncMock(side_effect=classify))
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        resources = WorkflowResources(
            boundaries,
            AsyncMock(),
            "panoptes",
            client,
            asyncio.Lock(),
            0,
            classifier=classifier,
        )
        summary = await execute_request(resources, request, context, uuid4())
    classifier.classify.assert_awaited_once()
    assert product_repository.save_product.await_count == (
        1 if decision == "accepted" else 0
    )
    assert summary["products"][0]["status"] == (
        "completed" if decision == "accepted" else decision
    )
    assert "stripbooks" not in visited[0]


async def test_discovery_enters_only_accepted_distinct_products_and_stores_images(
    boundaries,
):
    visited = []

    def response(request):
        visited.append(request.url.path)
        if request.url.path == "/s":
            data = (FIXTURES / "search.html").read_bytes()
            content_type = "text/html; charset=utf-8"
        elif request.url.host == "m.media-amazon.com":
            data, content_type = b"\x89PNG\r\n\x1a\nsynthetic", "image/png"
        else:
            data = (FIXTURES / "product.html").read_bytes()
            if request.url.path == "/dp/B07XW76VHZ":
                data = data.replace(b"1492040347", b"B07XW76VHZ")
            content_type = "text/html; charset=utf-8"
        return httpx.Response(200, content=data, headers={"content-type": content_type})

    storage = AsyncMock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        resources = WorkflowResources(
            boundaries, storage, "panoptes", client, asyncio.Lock(), 0
        )
        request, context = request_context()
        summary = await execute_request(resources, request, context, uuid4())
    assert "/dp/193693017X" not in visited
    assert "/dp/B012345678" not in visited
    assert visited.count("/dp/1492040347") == 1
    assert visited.count("/dp/B07XW76VHZ") == 1
    assert product_repository.save_product.await_count == 2
    assert sum(row["status"] == "completed" for row in summary["products"]) == 2
    image_calls = [
        call
        for call in storage.put_object.await_args_list
        if call.kwargs["ContentType"].startswith("image/")
    ]
    assert len(image_calls) == 2
    assert all(call.kwargs["Body"].startswith(b"\x89PNG") for call in image_calls)


async def test_refresh_skips_search_and_preserves_new_observation(boundaries):
    visited = []

    def response(request):
        visited.append(request.url.path)
        if request.url.host == "m.media-amazon.com":
            return httpx.Response(
                200, content=b"image", headers={"content-type": "image/jpeg"}
            )
        return httpx.Response(
            200,
            content=(FIXTURES / "product.html").read_bytes(),
            headers={"content-type": "text/html; charset=utf-8"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        resources = WorkflowResources(
            boundaries, AsyncMock(), "panoptes", client, asyncio.Lock(), 0
        )
        request, context = request_context("refresh")
        summary = await execute_request(resources, request, context, uuid4())
    assert "/s" not in visited
    assert summary["products"][0]["status"] == "completed"
    product_repository.save_product.assert_awaited_once()


async def test_changed_product_author_is_rejected_after_detail_fetch(boundaries):
    html = (
        (FIXTURES / "product.html")
        .read_bytes()
        .replace(b"Alex Petrov", b"Different Author")
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, content=html, headers={"content-type": "text/html; charset=utf-8"}
            )
        )
    ) as client:
        resources = WorkflowResources(
            boundaries, AsyncMock(), "panoptes", client, asyncio.Lock(), 0
        )
        request, context = request_context("refresh")
        summary = await execute_request(resources, request, context, uuid4())
    assert summary["products"][0]["status"] == "rejected"
    assert summary["products"][0]["reason"] == "author_mismatch"
    product_repository.save_product.assert_not_awaited()


@pytest.mark.parametrize("unknown_spec", [False, True])
async def test_profile_workflow_tracks_only_confirmed_first_scrapes(
    boundaries, unknown_spec
):
    html = (FIXTURES / "product.html").read_bytes()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, content=html, headers={"content-type": "text/html; charset=utf-8"}
            )
        )
    ) as client:
        resources = WorkflowResources(
            boundaries, AsyncMock(), "panoptes", client, asyncio.Lock(), 0
        )
        request, context = request_context("refresh")
        context["criteria"] = {
            "match_mode": "profile",
            "category": "book",
            "title": "Database Internals",
            "authors": ["Alex Petrov"],
            "reference_price": "100",
            "characteristics": [
                {"name": "Peso inexistente", "value": "2", "unit": "kg"}
            ]
            if unknown_spec
            else [],
        }
        summary = await execute_request(resources, request, context, uuid4())
    validation = capture_repository.save_detail_validation.await_args.args[3]
    assert validation.validator_version == "product_qualification/1.1.0"
    assert validation.checks
    if unknown_spec:
        assert summary["products"][0]["status"] == "uncertain"
        product_repository.save_product.assert_not_awaited()
    else:
        assert summary["products"][0]["status"] == "completed"
        product_repository.save_product.assert_awaited_once()


async def test_captcha_html_is_archived_and_stops_discovery(boundaries):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                content=b'<form action="validateCaptcha">captcha</form>',
                headers={"content-type": "text/html"},
            )
        )
    ) as client:
        storage = AsyncMock()
        resources = WorkflowResources(
            boundaries, storage, "panoptes", client, asyncio.Lock(), 0
        )
        request, context = request_context()
        with pytest.raises(PageBlockedError) as caught:
            await execute_request(resources, request, context, uuid4())
        assert caught.value.details["cause"] == "captcha"
        assert caught.value.details["http_status"] == 200
        assert caught.value.details["snapshot_id"]
    storage.put_object.assert_awaited_once()
    product_repository.save_product.assert_not_awaited()


@pytest.mark.parametrize("recovers", [True, False])
@pytest.mark.parametrize("error_status", [500, 502, 503, 504])
async def test_unavailable_page_retries_and_archives_each_attempt(
    boundaries, monkeypatch, recovers, error_status, capsys
):
    from panoptes_workers.workflow import service

    sleep = AsyncMock()
    monkeypatch.setattr(service.asyncio, "sleep", sleep)
    calls = []

    def response(request):
        calls.append(str(request.url))
        status = 200 if recovers and len(calls) == 2 else error_status
        return httpx.Response(
            status,
            content=b"Algo deu errado" if status != 200 else b"<html></html>",
            headers={"content-type": "text/html"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        storage = AsyncMock()
        resources = WorkflowResources(
            boundaries, storage, "panoptes", client, asyncio.Lock(), 0
        )
        request, _ = request_context()
        calls_url = "https://www.amazon.com.br/s?k=CTO"
        if recovers:
            page, _ = await fetch_page(
                resources,
                request,
                uuid4(),
                calls_url,
            )
            assert page.status == 200
        else:
            with pytest.raises(PageUnavailableError) as caught:
                await fetch_page(resources, request, uuid4(), calls_url)
            assert caught.value.details["http_status"] == error_status
            assert caught.value.details["attempt"] == 3
        expected = 2 if recovers else 3
        assert calls == [calls_url] * expected
        assert storage.put_object.await_count == expected
        assert capture_repository.save_snapshot.await_count == expected
        assert '"event": "source_page_fetched"' in capsys.readouterr().out


async def test_reclaimed_request_does_not_repeat_completed_refresh(
    boundaries, monkeypatch
):
    monkeypatch.setattr(
        capture_repository, "observed_keys", AsyncMock(return_value={"1492040347"})
    )
    client = AsyncMock()
    resources = WorkflowResources(
        boundaries, AsyncMock(), "panoptes", client, asyncio.Lock(), 0
    )
    request, context = request_context("refresh")
    result = await execute_request(resources, request, context, uuid4())
    assert result["products"][0]["recovered"]
    client.stream.assert_not_called()


async def test_mercado_livre_discovery_and_refresh_use_shared_pipeline(boundaries):
    folder = FIXTURES.parent / "mercado-livre-product"
    visited = []

    def response(request):
        visited.append(str(request.url))
        if request.url.host == "lista.mercadolivre.com.br":
            body = (folder / "search.html").read_bytes()
        elif request.url.host == "http2.mlstatic.com":
            return httpx.Response(
                200, content=b"image", headers={"content-type": "image/webp"}
            )
        else:
            body = (folder / "book.html").read_bytes()
            if "/p/" in request.url.path:
                body = body.replace(b"MLB1234567890", b"MLB9876543210").replace(
                    b"https://produto.mercadolivre.com.br/MLB-1234567890-livro-cto-_JM",
                    b"https://www.mercadolivre.com.br/livro-cto/p/MLB9876543210",
                )
        return httpx.Response(
            200, content=body, headers={"content-type": "text/html; charset=utf-8"}
        )

    request, context = request_context()
    context.update(site="mercado_livre_br", term="CTO livro", criteria={"title": "CTO"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        resources = WorkflowResources(
            boundaries, AsyncMock(), "panoptes", client, asyncio.Lock(), 0
        )
        result = await execute_request(resources, request, context, uuid4())
        assert sum(p["status"] == "completed" for p in result["products"]) == 2
        assert not any("amazon" in u or "1111111111" in u for u in visited)
        assert all(
            call.args[2].parser_slug == "mercado-livre-product"
            for call in product_repository.save_job.await_args_list
        )
        assert all(
            call.args[2]["site"] == "mercado_livre_br"
            for call in product_repository.save_product.await_args_list
        )
        visited.clear()
        request["mode"] = "refresh"
        context.update(
            source_key="MLB1234567890",
            product_url="https://produto.mercadolivre.com.br/MLB-1234567890-livro-cto-_JM",
        )
        result = await execute_request(resources, request, context, uuid4())
        assert result["products"][0]["status"] == "completed"
        assert not any("lista.mercadolivre" in u for u in visited)


async def test_mercado_livre_account_verification_is_archived_as_blocked(boundaries):
    visited = []

    def response(request):
        visited.append(str(request.url))
        if request.url.host == "lista.mercadolivre.com.br":
            return httpx.Response(
                302,
                headers={
                    "location": "https://www.mercadolivre.com.br/gz/account-verification?go=synthetic"
                },
            )
        return httpx.Response(
            200,
            content=b"<html>Verifique sua conta</html>",
            headers={"content-type": "text/html"},
        )

    request, context = request_context()
    context.update(site="mercado_livre_br", term="CTO livro", criteria={"title": "CTO"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        storage = AsyncMock()
        resources = WorkflowResources(
            boundaries, storage, "panoptes", client, asyncio.Lock(), 0
        )
        with pytest.raises(PageBlockedError) as caught:
            await execute_request(resources, request, context, uuid4())
    assert caught.value.reason == "mercado_livre_blocked"
    assert caught.value.details["cause"] == "account_verification_required"
    assert caught.value.details["site"] == "mercado_livre_br"
    storage.put_object.assert_awaited_once()
    assert len(visited) == 2
    product_repository.save_product.assert_not_awaited()


async def test_later_search_failure_preserves_completed_products(
    boundaries, monkeypatch
):
    from panoptes_workers.workflow import runner, service

    monkeypatch.setattr(service.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(
        service, "extract_product", AsyncMock(return_value={"status": "completed"})
    )

    def response(request):
        if "page=2" in str(request.url):
            return httpx.Response(503, content=b"Algo deu errado")
        return httpx.Response(
            200,
            content=(FIXTURES / "search.html").read_bytes(),
            headers={"content-type": "text/html"},
        )

    request, context = request_context()
    context["max_pages_qt"] = 2
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        resources = WorkflowResources(
            boundaries, AsyncMock(), "panoptes", client, asyncio.Lock(), 0
        )
        with pytest.raises(PageUnavailableError) as caught:
            await execute_request(resources, request, context, uuid4())
        assert (
            sum(
                row["status"] == "completed" for row in caught.value.details["products"]
            )
            == 2
        )

        monkeypatch.setattr(
            queue_repository, "read_context", AsyncMock(return_value=context)
        )
        monkeypatch.setattr(
            product_repository,
            "register_runtime",
            AsyncMock(return_value=({"public_id": uuid4()}, None)),
        )
        monkeypatch.setattr(
            runner, "execute_request", AsyncMock(side_effect=caught.value)
        )
        monkeypatch.setattr(queue_repository, "finish", AsyncMock())

        async def keepalive(*_):
            await asyncio.Event().wait()

        monkeypatch.setattr(runner, "heartbeat", keepalive)
        await runner.process(resources, request, uuid4())
        args = queue_repository.finish.await_args.args
        assert args[3] == "partial"
        assert args[4]["reason"] == "amazon_unavailable"
        assert args[4]["products"] == caught.value.details["products"]


async def test_later_search_parser_failure_preserves_completed_products(
    boundaries, monkeypatch
):
    from panoptes_workers.workflow import runner, service

    monkeypatch.setattr(
        service, "extract_product", AsyncMock(return_value={"status": "completed"})
    )

    def response(request):
        return httpx.Response(
            200,
            content=b"<html>Unexpected page</html>"
            if "page=2" in str(request.url)
            else (FIXTURES / "search.html").read_bytes(),
            headers={"content-type": "text/html"},
        )

    request, context = request_context()
    context["max_pages_qt"] = 2
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        resources = WorkflowResources(
            boundaries, AsyncMock(), "panoptes", client, asyncio.Lock(), 0
        )
        with pytest.raises(service.DiscoveryInterruptedError) as caught:
            await execute_request(resources, request, context, uuid4())
        assert sum(p["status"] == "completed" for p in caught.value.products) == 2
        monkeypatch.setattr(
            queue_repository, "read_context", AsyncMock(return_value=context)
        )
        monkeypatch.setattr(
            product_repository,
            "register_runtime",
            AsyncMock(return_value=({"public_id": uuid4()}, None)),
        )
        monkeypatch.setattr(
            runner, "execute_request", AsyncMock(side_effect=caught.value)
        )
        monkeypatch.setattr(queue_repository, "finish", AsyncMock())

        async def keepalive(*_):
            await asyncio.Event().wait()

        monkeypatch.setattr(runner, "heartbeat", keepalive)
        await runner.process(resources, request, uuid4())
        args = queue_repository.finish.await_args.args
        assert args[3] == "partial"
        assert args[4]["reason"] == "search_layout_not_recognized"
        assert args[4]["products"] == caught.value.products


async def test_missing_ml_pagination_preserves_first_page_as_partial(
    boundaries, monkeypatch
):
    from panoptes_workers.workflow import service

    visited = []
    html = (
        Path(__file__).resolve().parents[1]
        / "workers/parsers/mercado-livre-product/search.html"
    ).read_text()
    from selectolax.lexbor import LexborHTMLParser

    tree = LexborHTMLParser(html)
    del tree.css_first(".andes-pagination__button--next a").attrs["href"]

    def response(request):
        visited.append(str(request.url))
        return httpx.Response(
            200, text=tree.html, headers={"content-type": "text/html"}
        )

    monkeypatch.setattr(
        service, "extract_product", AsyncMock(return_value={"status": "completed"})
    )
    request, context = request_context()
    context.update(
        site="mercado_livre_br", term="CTO", max_pages_qt=3, criteria={"title": "CTO"}
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        summary = await execute_request(
            WorkflowResources(
                boundaries, AsyncMock(), "panoptes", client, asyncio.Lock(), 0
            ),
            request,
            context,
            uuid4(),
        )
    assert len(visited) == 1
    assert summary["truncated"] is True
    assert summary["reason"] == "pagination_url_unavailable"
    assert sum(p["status"] == "completed" for p in summary["products"]) == 2


@pytest.mark.parametrize(
    "product_status,reason",
    [("rejected", "product_type_mismatch"), ("uncertain", "classifier_failed")],
)
async def test_refresh_validation_failure_keeps_reason_in_summary_and_final_log(
    boundaries, monkeypatch, product_status, reason
):
    from panoptes_workers.workflow import runner

    request, context = request_context("refresh")
    monkeypatch.setattr(
        queue_repository, "read_context", AsyncMock(return_value=context)
    )
    monkeypatch.setattr(
        product_repository,
        "register_runtime",
        AsyncMock(return_value=({"public_id": uuid4()}, None)),
    )
    monkeypatch.setattr(
        runner,
        "execute_request",
        AsyncMock(
            return_value={"products": [{"status": product_status, "reason": reason}]}
        ),
    )
    monkeypatch.setattr(queue_repository, "finish", AsyncMock())
    sink = AsyncMock()
    resources = WorkflowResources(
        boundaries, AsyncMock(), "panoptes", None, asyncio.Lock(), 0, events=sink
    )
    await runner.process(resources, request, uuid4())
    args = queue_repository.finish.await_args.args
    assert args[3] == "failed"
    assert args[4]["reason"] == reason
    assert args[4]["product_status"] == product_status
    assert args[4].get("tracking_paused", False) == (product_status == "rejected")
    event = sink.write.await_args_list[-1].args[1]
    assert event["event"] == "extraction_finished"
    assert event["details"]["reason"] == reason
    assert event["details"]["product_status"] == product_status


@pytest.mark.parametrize("paused", [True, False])
async def test_finish_updates_tracking_with_validation_outcome(monkeypatch, paused):
    monkeypatch.setattr(queue_repository, "guard", AsyncMock())
    session = MagicMock(execute=AsyncMock())
    await queue_repository.finish(
        session, 7, uuid4(), "failed", {"tracking_paused": paused}
    )
    update = session.execute.await_args_list[-1]
    assert "enabled = CASE WHEN :pause_tracking" in str(update.args[0])
    assert update.args[1] == {"id": 7, "pause_tracking": paused}


async def test_context_failure_is_finished_and_logged(boundaries, monkeypatch):
    from panoptes_workers.workflow import runner

    monkeypatch.setattr(
        queue_repository,
        "read_context",
        AsyncMock(side_effect=ValueError("context_missing")),
    )
    monkeypatch.setattr(queue_repository, "finish", AsyncMock())
    sink = AsyncMock()
    resources = WorkflowResources(
        boundaries, AsyncMock(), "panoptes", None, asyncio.Lock(), 0, events=sink
    )
    request, _ = request_context()
    await runner.process(resources, request, uuid4())
    assert queue_repository.finish.await_args.args[3] == "failed"
    assert queue_repository.finish.await_args.args[4]["reason"] == "context_missing"
    entries = [call.args[1] for call in sink.write.await_args_list]
    assert [entry["event"] for entry in entries] == [
        "extraction_started",
        "extraction_failed",
        "extraction_finished",
    ]


async def test_http_200_captcha_capture_is_blocked_before_parsing(boundaries):
    from panoptes_workers.infrastructure.http import Download, block_reason

    body = (FIXTURES.parent / "mercado-livre-product/captcha-wall.html").read_bytes()
    page = Download(
        "https://lista.mercadolivre.com.br/sofa",
        "https://www.mercadolivre.com.br/captcha/wall/logged",
        body,
        200,
        "text/html",
    )
    assert block_reason(page) == "captcha"
    assert (
        block_reason(Download(page.source_url, page.source_url, body, 200, "text/html"))
        == "captcha"
    )
    assert (
        block_reason(
            Download(
                page.source_url,
                page.source_url,
                b'<html><script>"Por seguran\xc3\xa7a, complete esta etapa"</script><div class="ui-search-results"></div></html>',
                200,
                "text/html",
            )
        )
        is None
    )
    browser = AsyncMock()
    browser.fetch.return_value = {
        "blocked": "verification_required",
        "cause": "captcha",
    }
    request, _ = request_context()
    resources = WorkflowResources(
        boundaries, AsyncMock(), "panoptes", None, asyncio.Lock(), 0, browser=browser
    )
    with pytest.raises(PageBlockedError) as caught:
        await fetch_page(resources, request, uuid4(), page.source_url)
    assert caught.value.details["cause"] == "captcha"
    resources.storage.put_object.assert_not_awaited()


@pytest.mark.parametrize("mode,stage", [("discover", "search"), ("refresh", "product")])
async def test_parser_failure_preserves_html_and_links_s3_capture(
    boundaries, monkeypatch, mode, stage
):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from panoptes_workers.workflow import service

    source = service.get_source("amazon_br")
    failing = SimpleNamespace(
        definition=source.definition,
        parser_version=source.parser_version,
        search_url=source.search_url,
        parse_search=Mock(side_effect=ValueError("search_layout_not_recognized")),
        parse_product=Mock(side_effect=ValueError("product_layout_not_recognized")),
    )
    monkeypatch.setattr(service, "get_source", lambda _: failing)
    body = b"<html><body>Unexpected but preserved page</body></html>"
    storage, sink = AsyncMock(), AsyncMock()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, content=body, headers={"content-type": "text/html"}
            )
        )
    ) as client:
        resources = WorkflowResources(
            boundaries, storage, "panoptes", client, asyncio.Lock(), 0, events=sink
        )
        request, context = request_context(mode)
        with pytest.raises(ValueError):
            await execute_request(resources, request, context, uuid4())
    storage.put_object.assert_awaited_once()
    assert storage.put_object.await_args.kwargs["Body"] == body
    failure = next(
        call.args[1]
        for call in sink.write.await_args_list
        if call.args[1]["event"] == "parser_failed"
    )
    assert failure["details"]["stage"] == stage
    assert failure["details"]["asset_id"]
    assert failure["details"]["snapshot_id"]
    assert failure["details"]["sha256"]
    assert failure["details"]["bytes"] == len(body)
    assert failure["details"]["parser_version"] == source.parser_version
    capture_repository.save_snapshot.assert_awaited_once()
    product_repository.save_product.assert_not_awaited()


async def test_category_workflow_discovers_multiple_models_and_refreshes_directly(
    boundaries,
):
    folder = FIXTURES.parent / "amazon-product"
    visited = []

    def response(request):
        visited.append(str(request.url))
        if request.url.path == "/s":
            assert "stripbooks" not in request.url.params.values()
            data = (folder / "search.html").read_bytes()
        else:
            asin = request.url.path.rsplit("/", 1)[-1]
            data = (
                (folder / "television.html")
                .read_bytes()
                .replace(b"B0TV500001", asin.encode())
            )
            if asin == "B0TV500002":
                data = data.replace(b"S50C100", b"S50Q200").replace(
                    b"Crystal UHD 4K", b"QLED"
                )
            elif asin == "B0TV500003":
                data = data.replace(b"Samsung", b"LG").replace(b"S50C100", b"L50U300")
            elif asin == "B0TV500004":
                data = data.replace(b"S50C100", b"S50C400")
        return httpx.Response(
            200, content=data, headers={"content-type": "text/html; charset=utf-8"}
        )

    request, context = request_context()
    context.update(
        term="tv 50 polegadas",
        criteria={
            "match_mode": "category",
            "category": "television",
            "required_attributes": {"screen_size_inches": 50},
        },
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        resources = WorkflowResources(
            boundaries, AsyncMock(), "panoptes", client, asyncio.Lock(), 0
        )
        result = await execute_request(resources, request, context, uuid4())
        assert sum(p["status"] == "completed" for p in result["products"]) == 4
        assert not any(
            "/dp/B0TV550001" in url or "/dp/B0AC500001" in url for url in visited
        )
        details = [
            call.args[3] for call in product_repository.save_product.await_args_list
        ]
        assert {d.catalog.brand for d in details} == {"LG", "Samsung"}
        assert len({d.catalog.model for d in details}) == 4
        visited.clear()
        product_repository.save_product.reset_mock()
        request["mode"] = "refresh"
        context.update(
            source_key="B0TV500003",
            product_url="https://www.amazon.com.br/dp/B0TV500003",
        )
        result = await execute_request(resources, request, context, uuid4())
        assert result["products"][0]["status"] == "completed"
        assert len(visited) == 1 and "/s?" not in visited[0]
        product_repository.save_product.assert_awaited_once()
