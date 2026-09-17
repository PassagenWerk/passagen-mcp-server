[Passagen MCP Server](https://github.com/PassagenWerk/passagen-mcp-server) exposes an existing
Passagen paper library to Model Context Protocol clients and Agent Hosts. It supports projected
paper discovery, stable offset pagination, bulk paper resolution, paper context, page-linked
full-text search, citations, collections, tags, synthesis, reports, and collection documents.

The server is read-only by default. Trusted deployments can enable bounded organization writes
for collections, tags, paper-tag assignments, and Markdown documents. It does not import or delete
papers, run processing, or generate research artifacts.

## Quick Start

The `0.3` image requires a Passagen Core `0.9` library using Schema version 13.

```bash
export PASSAGEN_MCP_TOKEN="$(openssl rand -hex 32)"

docker run --rm \
  -p 127.0.0.1:8766:8766 \
  -e PASSAGEN_MCP_TOKEN="$PASSAGEN_MCP_TOKEN" \
  -v /absolute/path/to/passagen-library:/data:ro \
  docker.io/sycstudio/passagen-mcp-server:0.3.0 \
  passagen-mcp serve \
  --data-dir /data \
  --host 0.0.0.0 \
  --port 8766 \
  --allow-host localhost \
  --allow-host 127.0.0.1
```

Connect the client to `http://127.0.0.1:8766/mcp` with:

```text
Authorization: Bearer <PASSAGEN_MCP_TOKEN>
```

Do not expose the built-in plain HTTP endpoint to an untrusted network. Use a TLS reverse proxy
for remote access.

## Optional Writes

Add `--allow-write` to the server command and mount `/data` read-write. HTTP write mode always
requires a Bearer token. Keep this disabled for untrusted clients.

## Image Tags

- `0.3.0`: fixed release
- `0.3`: current `0.3` release line
- `latest`: latest stable release

Supported platforms:

- `linux/amd64`
- `linux/arm64`

## Health Check

```bash
curl http://127.0.0.1:8766/health
```

## Documentation

- [Repository and full usage guide](https://github.com/PassagenWerk/passagen-mcp-server)
- [LibreChat deployment](https://github.com/PassagenWerk/passagen-mcp-server/blob/main/docs/librechat.md)
- [Passagen Web](https://github.com/PassagenWerk/passagen-web)

Passagen MCP Server is licensed under GNU AGPL-3.0-only.
