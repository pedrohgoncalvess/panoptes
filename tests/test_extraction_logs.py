import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from panoptes_backend.management import logs
from panoptes_workers.infrastructure.events import emit, failure_details, safe_details


def test_log_details_remove_credentials_and_url_queries():
    result = safe_details(
        {
            "cookies": "private",
            "password": "private",
            "nested": {
                "authorization": "private",
                "source_url": "https://user:private@example.com/path?token=private#private",
            },
            "stack": [{"function": "parse_search"}],
        }
    )
    assert "private" not in json.dumps(result)
    assert result["nested"]["source_url"] == "https://example.com/path"
    assert result["stack"][0]["function"] == "parse_search"


def test_failures_preserve_parser_code_but_not_arbitrary_exception_text():
    assert (
        failure_details(ValueError("search_layout_not_recognized"))["reason"]
        == "search_layout_not_recognized"
    )
    assert "private" not in json.dumps(
        failure_details(ValueError("SQL params password=private"))
    )


async def test_logging_failure_does_not_interrupt_extraction(capsys):
    sink = SimpleNamespace(write=AsyncMock(side_effect=RuntimeError("private")))
    request = {"id": 1, "public_id": uuid4(), "correlation_id": uuid4()}
    await emit(
        SimpleNamespace(events=sink),
        request,
        "test",
        "Etapa concluída.",
        cookies="private",
        attempt=2,
    )
    output = capsys.readouterr().out
    assert "private" not in output
    assert "log_persistence_failed" in output
    assert sink.write.await_args.args[1]["details"] == {"attempt": 2}


async def test_sse_replays_in_order_and_releases_query_between_batches(monkeypatch):
    read = AsyncMock(
        side_effect=[
            [
                {"id": 9, "message": "Página recebida"},
                {"id": 10, "message": "Interpretando busca"},
            ],
            [],
        ]
    )
    monkeypatch.setattr(logs, "read_logs", read)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(sessions=object())),
        is_disconnected=AsyncMock(side_effect=[False, False, True]),
    )
    frames = [
        frame
        async for frame in logs.stream_logs(
            request, 8, {"site": "mercado_livre_br"}, pause=AsyncMock()
        )
    ]
    assert frames[0].startswith("retry:")
    assert "id: 9\nevent: log\n" in frames[1]
    assert "id: 10\nevent: log\n" in frames[2]
    assert read.await_args_list[0].kwargs["after"] == 8
    assert read.await_args_list[1].kwargs["after"] == 10


async def test_sse_last_event_id_takes_precedence_and_rejects_invalid_cursor(
    monkeypatch,
):
    seen = []

    async def fake_stream(request, cursor, filters):
        seen.append((cursor, filters))
        yield "retry: 3000\n\n"

    monkeypatch.setattr(logs, "stream_logs", fake_stream)
    request = SimpleNamespace(headers={"Last-Event-ID": "42"})
    response = await logs.stream(
        request, after=10, request_id=None, site="amazon_br", level="ERROR"
    )
    assert response.media_type == "text/event-stream"
    assert response.headers["x-accel-buffering"] == "no"
    assert [frame async for frame in response.body_iterator]
    assert seen[0] == (42, {"request_id": None, "site": "amazon_br", "level": "ERROR"})
    request.headers = {"Last-Event-ID": "-1"}
    with pytest.raises(HTTPException) as caught:
        await logs.stream(request, after=0, request_id=None, site=None, level=None)
    assert caught.value.status_code == 422


async def test_history_uses_latest_window_and_filtered_cursor(monkeypatch):
    read = AsyncMock(return_value=[{"id": 10}, {"id": 14}, {"id": 18}])
    monkeypatch.setattr(logs, "read_logs", read)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(sessions=object()))
    )
    result = await logs.history(
        request,
        request_id=None,
        site="mercado_livre_br",
        level="ERROR",
        before=20,
        limit=2,
    )
    assert result == {"items": [{"id": 14}, {"id": 18}], "cursor": 18, "has_more": True}
    assert read.await_args.kwargs["before"] == 20
    assert read.await_args.kwargs["latest"] is True


async def test_history_last_page_has_no_next_page(monkeypatch):
    monkeypatch.setattr(
        logs, "read_logs", AsyncMock(return_value=[{"id": 14}, {"id": 18}])
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(sessions=object()))
    )
    result = await logs.history(
        request, request_id=None, site=None, level=None, before=20, limit=2
    )
    assert result["has_more"] is False
    assert result["items"] == [{"id": 14}, {"id": 18}]
