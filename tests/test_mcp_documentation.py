"""Validate the documentation as seen by an MCP client, including chained examples."""

import json
import re
from importlib.resources import files
from pathlib import Path
from unittest.mock import AsyncMock

from jsonschema import Draft202012Validator
from mcp.shared.memory import create_connected_server_and_client_session
from panoptes_mcp.instructions import GUIDE
from panoptes_mcp.models import CreateTerms, RoutineUpdate
from panoptes_mcp.responses import SearchPage
from panoptes_mcp.server import create_server

TERM = "11111111-1111-4111-8111-111111111111"
ENTITY = "22222222-2222-4222-8222-222222222222"
OBSERVATION = "33333333-3333-4333-8333-333333333333"
OFFER = "44444444-4444-4444-8444-444444444444"
REQUEST = "55555555-5555-4555-8555-555555555555"
ROUTINE = "66666666-6666-4666-8666-666666666666"
AT = "2026-10-24T12:00:00-03:00"


def examples():
    return [
        json.loads(value) for value in re.findall(r"```json\n(.*?)\n```", GUIDE, re.S)
    ]


async def test_all_tools_publish_outputs_and_guide_contains_live_schemas():
    async with create_connected_server_and_client_session(
        create_server(AsyncMock)
    ) as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        assert len(tools) == 33
        assert all(tool.outputSchema for tool in tools.values())
        guide = await session.call_tool("get_usage_guide", {})
        resource = await session.read_resource("panoptes://guide")
        assert guide.structuredContent["result"] == resource.contents[0].text == GUIDE
        for name in [
            "search_products",
            "create_search_terms",
            "update_routine",
            "price_details",
        ]:
            result = await session.call_tool("get_usage_guide", {"tool_name": name})
            schemas = json.loads(
                re.findall(
                    r"```json\n(.*?)\n```", result.structuredContent["result"], re.S
                )[-1]
            )
            assert schemas["inputSchema"] == tools[name].inputSchema
            assert schemas["outputSchema"] == tools[name].outputSchema
        assert (
            await session.call_tool("get_usage_guide", {"tool_name": "invented"})
        ).isError
        inputs = tools["search_products"].inputSchema["properties"]
        assert "entity_id" in tools["get_product_history"].inputSchema["properties"]
        assert "exatas" in json.dumps(inputs["term_id"], ensure_ascii=False)
        assert "lower(btrim(term))" in json.dumps(
            tools["price_details"].inputSchema["properties"]["term_id"],
            ensure_ascii=False,
        )
        assert (
            "list_canonical_products"
            in tools["list_canonical_listings"].inputSchema["properties"]["product_id"][
                "description"
            ]
        )


async def test_documented_json_examples_validate_against_published_schemas():
    values = examples()
    assert len(values) == 6
    names = [
        "search_products",
        None,
        "get_product_history",
        "create_search_terms",
        "get_scrape_request",
        "update_routine",
    ]
    async with create_connected_server_and_client_session(
        create_server(AsyncMock)
    ) as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        for value, name in zip(values, names, strict=True):
            if name is None:
                SearchPage.model_validate(value)
                Draft202012Validator(tools["search_products"].outputSchema).validate(
                    value
                )
            else:
                Draft202012Validator(tools[name].inputSchema).validate(value)
        CreateTerms.model_validate(values[3]["value"])
        RoutineUpdate.model_validate(values[5]["value"])


def test_repository_documentation_contains_the_exact_packaged_guide():
    documentation = Path(__file__).parents[1] / "docs" / "mcp.md"
    assert GUIDE in documentation.read_text(encoding="utf-8")
    assert files("panoptes_mcp").joinpath("guide.md").is_file()
    for topic in [
        "lower(btrim(term))",
        "is_current=false",
        "enabled",
        "5, 10, 20",
        "structuredContent",
    ]:
        assert topic in GUIDE


async def test_documented_workflow_uses_returned_ids_and_structured_results():
    (
        search_args,
        search_response,
        history_args,
        create_args,
        request_args,
        pause_args,
    ) = examples()
    routine = {
        "public_id": ROUTINE,
        "name": "Novas GPUs",
        "search_term_id": TERM,
        "term": "RTX 5070",
        "site": "kabum_br",
        "mode": "discover",
        "schedule": pause_args["value"]["schedule"],
        "enabled": True,
        "next_run_at": AT,
        "created_at": AT,
        "sites": ["kabum_br", "pichau_br"],
    }

    async def respond(method, path, *, params=None, body=None):
        if path == "/search-terms":
            return [
                {
                    "public_id": TERM,
                    "site": "kabum_br",
                    "term": "RTX 5070",
                    "criteria": {"match_mode": "intent", "query": "RTX 5070"},
                    "max_pages_qt": 2,
                    "max_candidates_qt": 100,
                    "refresh_interval_seconds": 86400,
                    "created_at": AT,
                }
            ]
        if path == "/products/search":
            assert str(params["term_id"]) == TERM
            return search_response
        if path == f"/products/{ENTITY}/observations":
            return [
                {
                    "public_id": OBSERVATION,
                    "created_at": AT,
                    "payload": {"entity": {"title": "GPU"}},
                }
            ]
        if path == f"/products/{ENTITY}/offers":
            return [
                {
                    "public_id": OFFER,
                    "listing_entity_id": ENTITY,
                    "listing_id": ROUTINE,
                    "observation_id": OBSERVATION,
                    "observed_at": AT,
                    "price": None,
                    "currency": "BRL",
                    "seller": None,
                    "is_current": False,
                    "promotions": [],
                    "payment_options": [],
                    "shipping": None,
                }
            ]
        if path == f"/offers/{OFFER}/observations":
            return [
                {
                    "public_id": OBSERVATION,
                    "observed_at": AT,
                    "price": "4500.00",
                    "list_price": None,
                    "currency": "BRL",
                    "availability": None,
                    "promotions": [],
                    "payment_options": [],
                    "shipping": None,
                }
            ]
        if path == "/search-terms/batch":
            return {
                "terms": [
                    {
                        "public_id": TERM,
                        "site": "kabum_br",
                        "term": body["term"],
                        "criteria": {},
                        "max_pages": 2,
                        "max_candidates": 100,
                        "refresh_interval_seconds": 86400,
                    }
                ],
                "requests": [
                    {
                        "public_id": REQUEST,
                        "status": "pending",
                        "site": "kabum_br",
                        "search_term_id": TERM,
                    }
                ],
            }
        if path == f"/scrape-requests/{REQUEST}":
            return {
                "public_id": REQUEST,
                "status": "partial",
                "mode": "discover",
                "site": "kabum_br",
                "search_term_id": TERM,
                "entity_id": None,
                "term": "RTX 5070",
                "summary": {"reason": "some_candidates_failed"},
                "created_at": AT,
                "completed_at": AT,
            }
        if path == f"/routines/{ROUTINE}":
            return routine if method == "GET" else {**routine, **body}
        raise AssertionError((method, path))

    api = AsyncMock()
    api.request.side_effect = respond
    async with create_connected_server_and_client_session(
        create_server(lambda: api)
    ) as session:

        async def call(name, arguments):
            result = await session.call_tool(name, arguments)
            assert not result.isError, result.content
            return result.structuredContent

        terms = await call("list_search_terms", {"q": "RTX 5070", "site": "kabum_br"})
        search_args["term_id"] = terms["result"][0]["public_id"]
        page = await call("search_products", search_args)
        history_args["entity_id"] = page["items"][0]["public_id"]
        history = await call("get_product_history", history_args)
        assert history["result"][0]["public_id"] == OBSERVATION
        offers = await call(
            "list_product_offers", {"entity_id": history_args["entity_id"]}
        )
        assert offers["result"][0]["price"] is None
        assert not offers["result"][0]["is_current"]
        await call("get_offer_history", {"offer_id": offers["result"][0]["public_id"]})
        created = await call("create_search_terms", create_args)
        request_args["request_id"] = created["requests"][0]["public_id"]
        request = await call("get_scrape_request", request_args)
        assert request["status"] == "partial"
        current = await call("get_routine", {"routine_id": ROUTINE})
        pause_args["value"] = {
            key: current[key] for key in ["name", "schedule", "sites"]
        } | {"enabled": False}
        paused = await call("update_routine", pause_args)
        assert paused["enabled"] is False
        assert paused["schedule"] == current["schedule"]
        assert paused["sites"] == current["sites"]


async def test_output_contract_rejects_a_broken_backend_response():
    api = AsyncMock()
    api.request.return_value = {"items": [{"public_id": "not-a-uuid"}], "total": 1}
    async with create_connected_server_and_client_session(
        create_server(lambda: api)
    ) as session:
        assert (await session.call_tool("search_products", {"q": "gpu"})).isError
