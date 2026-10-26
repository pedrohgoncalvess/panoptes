import json
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.memory import create_connected_server_and_client_session
from panoptes_mcp.client import PanoptesClient
from panoptes_mcp.server import create_server


async def test_protocol_tools_resources_prompts_and_validation():
    api = AsyncMock()
    api.request.return_value = [{"id": "kabum_br", "name": "KaBuM!"}]
    async with create_connected_server_and_client_session(
        create_server(lambda: api)
    ) as session:
        tools = (await session.list_tools()).tools
        assert len(tools) == 33
        names = {tool.name: tool for tool in tools}
        assert names["search_products"].annotations.readOnlyHint
        assert not names["create_search_terms"].annotations.readOnlyHint
        assert all(tool.description and tool.inputSchema for tool in tools)
        assert "vector" not in json.dumps(names["search_products"].inputSchema)
        assert "password" not in json.dumps([tool.inputSchema for tool in tools])
        result = await session.call_tool("list_sources", {})
        assert not result.isError
        api.request.assert_awaited_with("GET", "/sources")
        guide = await session.read_resource("panoptes://guide")
        assert "start_at" in guide.contents[0].text
        prompts = await session.list_prompts()
        assert {p.name for p in prompts.prompts} == {
            "research_products",
            "plan_scraping",
        }
        assert (
            await session.get_prompt("research_products", {"question": "GPUs?"})
        ).messages
        for args in (
            {"q": "gpu", "limit": 101},
            {"q": "gpu", "offset": -1},
            {"q": "gpu", "start_at": "2026-10-01T00:00:00"},
            {"mode": "semantic"},
            {"mode": "recent", "q": "gpu"},
            {
                "mode": "recent",
                "start_at": "2026-10-02T00:00:00Z",
                "end_at": "2026-10-01T00:00:00Z",
            },
        ):
            assert (await session.call_tool("search_products", args)).isError
        api.request.reset_mock()
        for value in (
            {"term": "gpu", "sites": []},
            {"term": "gpu", "sites": ["kabum_br", "kabum_br"]},
            {"term": "gpu", "sites": ["unknown"]},
            {"term": "  ", "sites": ["kabum_br"]},
        ):
            assert (
                await session.call_tool("create_search_terms", {"value": value})
            ).isError
        api.request.assert_not_awaited()
    api.close.assert_awaited_once()


async def test_mcp_forwards_semantic_filters_and_creation():
    api = AsyncMock()
    api.request.return_value = {
        "items": [],
        "total": 0,
        "limit": 10,
        "offset": 20,
        "mode": "semantic",
    }
    term = str(uuid4())
    async with create_connected_server_and_client_session(
        create_server(lambda: api)
    ) as session:
        result = await session.call_tool(
            "search_products",
            {
                "q": "placa de vídeo",
                "term_id": term,
                "site": "kabum_br",
                "start_at": "2026-10-01T00:00:00-03:00",
                "limit": 10,
                "offset": 20,
            },
        )
        assert not result.isError
        call = api.request.await_args
        assert call.args == ("GET", "/products/search")
        assert call.kwargs["params"]["term_id"].hex == term.replace("-", "")
        assert call.kwargs["params"]["start_at"].utcoffset().total_seconds() == -10800
        assert call.kwargs["params"]["offset"] == 20
        api.request.return_value = {"terms": [], "requests": []}
        result = await session.call_tool(
            "create_search_terms",
            {
                "value": {
                    "term": "RTX 5070",
                    "description": "Excluir computadores",
                    "sites": ["kabum_br", "pichau_br"],
                    "discover": True,
                }
            },
        )
        assert not result.isError
        call = api.request.await_args
        assert call.args == ("POST", "/search-terms/batch")
        assert call.kwargs["body"]["description"] == "Excluir computadores"
        assert call.kwargs["body"]["discover"] is True


async def test_client_key_authentication_and_redacts_errors(monkeypatch):
    monkeypatch.setenv("PANOPTES_MCP_KEY", "pmcp_test-key")
    paths = []

    def handler(request):
        paths.append(request.url.path)
        assert request.headers["authorization"] == "Bearer pmcp_test-key"
        if request.url.path == "/expired":
            return httpx.Response(401)
        if request.url.path == "/bad":
            return httpx.Response(500, text="password=secret internal SQL")
        return httpx.Response(200, json=[{"id": "kabum_br"}])

    client = PanoptesClient(transport=httpx.MockTransport(handler))
    try:
        assert await client.request("GET", "/sources") == [{"id": "kabum_br"}]
        with pytest.raises(ToolError) as error:
            await client.request("GET", "/bad")
        assert "secret" not in str(error.value) and "SQL" not in str(error.value)
        with pytest.raises(ToolError, match="401"):
            await client.request("GET", "/expired")
        assert paths == ["/sources", "/bad", "/expired"]
    finally:
        await client.close()


async def test_client_requires_generated_key_even_with_password(monkeypatch):
    monkeypatch.delenv("PANOPTES_MCP_KEY", raising=False)
    monkeypatch.setenv("PANOPTES_EMAIL", "admin@panoptes.com")
    monkeypatch.setenv("PANOPTES_PASSWORD", "admin")
    client = PanoptesClient(
        transport=httpx.MockTransport(lambda r: pytest.fail("No request expected"))
    )
    try:
        with pytest.raises(ToolError, match="PANOPTES_MCP_KEY"):
            await client.request("GET", "/sources")
    finally:
        await client.close()


async def test_client_does_not_retry_writes_on_network_failure(monkeypatch):
    monkeypatch.setenv("PANOPTES_MCP_KEY", "pmcp_token")
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("private", request=request)

    client = PanoptesClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ToolError, match="indisponível"):
            await client.request("POST", "/search-terms/batch", body={})
        assert len(calls) == 1
    finally:
        await client.close()


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "http://remote.example", "https://user:pass@example.com"],
)
def test_rejects_unsafe_api_configuration(monkeypatch, url):
    monkeypatch.setenv("PANOPTES_API_URL", url)
    with pytest.raises(ValueError):
        PanoptesClient()
