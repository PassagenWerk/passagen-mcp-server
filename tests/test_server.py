from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters
from mcp.types import TextContent, TextResourceContents

from passagen_mcp.library import LibraryReader
from passagen_mcp.server import create_server


@pytest.mark.anyio
async def test_tools_return_structured_content(library: LibraryReader) -> None:
    server = create_server(library)
    async with Client(server, raise_exceptions=True) as client:
        listed = await client.list_tools()
        result = await client.call_tool("list_papers", {"title_query": "Alpha"})

    names = {tool.name for tool in listed.tools}
    assert names == {
        "list_papers",
        "get_paper_context",
        "search_paper_sections",
        "list_collections",
        "list_tags",
        "get_collection_context",
        "list_collection_reports",
        "get_collection_report",
    }
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in listed.tools)
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["items"][0]["id"] == "paper-a"


@pytest.mark.anyio
async def test_collection_write_tools_require_opt_in_and_return_updated_detail(
    library: LibraryReader,
) -> None:
    read_only_server = create_server(library)
    write_server = create_server(library, allow_write=True)

    async with Client(read_only_server, raise_exceptions=True) as client:
        read_only_tools = await client.list_tools()
    async with Client(write_server, raise_exceptions=True) as client:
        listed = await client.list_tools()
        created = await client.call_tool(
            "create_collection",
            {"name": "Agent Queue", "description": "Selected through MCP"},
        )
        assert created.structured_content is not None
        collection_id = created.structured_content["id"]
        updated = await client.call_tool(
            "add_papers_to_collection",
            {"collection_id": collection_id, "paper_ids": ["paper-c", "paper-a"]},
        )

    assert "create_collection" not in {tool.name for tool in read_only_tools.tools}
    tools = {tool.name: tool for tool in listed.tools}
    assert set(tools) >= {"create_collection", "add_papers_to_collection"}
    assert tools["create_collection"].annotations is not None
    assert tools["create_collection"].annotations.read_only_hint is False
    assert tools["create_collection"].annotations.destructive_hint is False
    assert tools["create_collection"].annotations.idempotent_hint is False
    assert tools["add_papers_to_collection"].annotations is not None
    assert tools["add_papers_to_collection"].annotations.idempotent_hint is True
    assert updated.structured_content is not None
    assert [item["paper"]["id"] for item in updated.structured_content["papers"]] == [
        "paper-c",
        "paper-a",
    ]


@pytest.mark.anyio
async def test_resources_read_validated_content(library: LibraryReader) -> None:
    server = create_server(library)
    async with Client(server, raise_exceptions=True) as client:
        templates = await client.list_resource_templates()
        summary = await client.read_resource("passagen://papers/paper-a/summary")
        section = await client.read_resource("passagen://papers/paper-a/sections/1")

    assert len(templates.resource_templates) == 8
    assert isinstance(summary.contents[0], TextResourceContents)
    assert isinstance(section.contents[0], TextResourceContents)
    summary_content = json.loads(summary.contents[0].text)
    section_content = json.loads(section.contents[0].text)
    assert summary_content["schema_version"] == "2"
    assert section_content["pages"] == [7, 8]


@pytest.mark.anyio
async def test_collection_intelligence_tools_and_resources(library: LibraryReader) -> None:
    collection_id = library.list_collections().items[0].id
    server = create_server(library)
    async with Client(server, raise_exceptions=True) as client:
        reports = await client.call_tool(
            "list_collection_reports", {"collection_id": collection_id}
        )
        synthesis = await client.read_resource(f"passagen://collections/{collection_id}/synthesis")
        report = await client.read_resource(
            f"passagen://collections/{collection_id}/reports/report-1"
        )

    assert reports.structured_content is not None
    assert reports.structured_content["items"][0]["id"] == "report-1"
    assert isinstance(synthesis.contents[0], TextResourceContents)
    assert isinstance(report.contents[0], TextResourceContents)
    assert json.loads(synthesis.contents[0].text)["synthesis"]["schema_version"] == "2"
    assert json.loads(report.contents[0].text)["report"]["title"] == "Latency review"


@pytest.mark.anyio
async def test_expected_tool_failure_is_visible_to_model(library: LibraryReader) -> None:
    server = create_server(library)
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("get_paper_context", {"paper_id": "missing"})

    assert result.is_error is True
    assert isinstance(result.content[0], TextContent)
    assert "Paper not found: missing" in result.content[0].text


@pytest.mark.anyio
async def test_missing_resource_uses_protocol_error(library: LibraryReader) -> None:
    server = create_server(library)
    async with Client(server, raise_exceptions=True) as client:
        with pytest.raises(Exception, match="Summary not found"):
            await client.read_resource("passagen://papers/paper-b/summary")


@pytest.mark.anyio
async def test_stdio_entrypoint_serves_real_client(data_dir: Path) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "passagen_mcp.cli",
            "stdio",
            "--data-dir",
            str(data_dir),
        ],
    )
    async with Client(parameters) as client:
        result = await client.call_tool("list_tags", {})

    assert result.is_error is False
    assert result.structured_content is not None
    assert {item["name"] for item in result.structured_content["items"]} == {
        "Priority",
        "Systems",
    }
