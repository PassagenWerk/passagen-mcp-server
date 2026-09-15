from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from mcp import Client
from starlette.testclient import TestClient

from passagen_mcp.config import ConfigurationError, HttpSettings
from passagen_mcp.library import LibraryReader
from passagen_mcp.server import create_http_app, create_server


def test_non_loopback_requires_token_and_host_allowlist() -> None:
    with pytest.raises(ConfigurationError, match="bearer token"):
        HttpSettings(host="0.0.0.0", allowed_hosts=("passagen-mcp:*",))
    with pytest.raises(ConfigurationError, match="allow-host"):
        HttpSettings(host="0.0.0.0", token="secret")


def test_collection_writes_require_token_even_on_loopback() -> None:
    with pytest.raises(ConfigurationError, match="collection writes"):
        HttpSettings(allow_write=True)

    settings = HttpSettings(token="secret", allow_write=True)

    assert settings.allow_write is True


def test_health_is_public_but_mcp_requires_bearer(data_dir: Path) -> None:
    server = create_server(LibraryReader(data_dir / "passagen.db", data_dir))
    settings = HttpSettings(token="secret", allowed_hosts=("testserver",), allowed_origins=())
    app = create_http_app(server, settings)

    with TestClient(app) as client:
        health = client.get("/health")
        unauthorized = client.post("/mcp", json={})
        authorized = client.post("/mcp", json={}, headers={"Authorization": "Bearer secret"})

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert unauthorized.status_code == 401
    assert unauthorized.headers["www-authenticate"] == "Bearer"
    assert authorized.status_code != 401


def test_transport_rejects_unknown_host(data_dir: Path) -> None:
    server = create_server(LibraryReader(data_dir / "passagen.db", data_dir))
    app = create_http_app(server, HttpSettings(allowed_hosts=("allowed.example",)))

    with TestClient(app, base_url="http://blocked.example") as client:
        response = client.post("/mcp", json={})

    assert response.status_code == 421


@pytest.mark.anyio
async def test_streamable_http_serves_real_mcp_client(data_dir: Path) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    mcp = create_server(LibraryReader(data_dir / "passagen.db", data_dir))
    app = create_http_app(mcp, HttpSettings(port=port))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.02)
        assert server.started
        async with Client(f"http://127.0.0.1:{port}/mcp") as client:
            result = await client.call_tool("list_collections", {})
        assert result.is_error is False
        assert result.structured_content is not None
        assert result.structured_content["items"][0]["name"] == "Reading Queue"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
