# LibreChat Deployment

Streamable HTTP is the recommended transport for LibreChat. The stdio transport works when
LibreChat can launch the server process and access the same data directory, but process-backed MCP
servers must be configured by an administrator and are harder to isolate in Docker.

## Docker Network

Build the image from this repository with the adjacent Core checkout as a named build context:

```bash
docker build \
  --build-context passagen-core=../passagen-core \
  -t passagen-mcp-server:local .
```

Run it on the same private Docker network as LibreChat. Mount the complete Passagen data directory
read-only where possible. SQLite may still create transient journal files for some operations, so
verify the actual library and filesystem mode used by your deployment.

```yaml
services:
  passagen-mcp:
    image: passagen-mcp-server:local
    restart: unless-stopped
    environment:
      PASSAGEN_MCP_TOKEN: ${PASSAGEN_MCP_TOKEN:?set PASSAGEN_MCP_TOKEN}
    volumes:
      - /srv/passagen/data:/data:ro
    networks:
      - librechat

networks:
  librechat:
    external: true
```

The image listens on `0.0.0.0:8766`, but the port does not need to be published to the host when
LibreChat shares the network.

## LibreChat Configuration

Add the server and its private Docker address to `librechat.yaml`:

```yaml
mcpSettings:
  allowedAddresses:
    - passagen-mcp:8766

mcpServers:
  passagen:
    title: Passagen Library
    description: Search and read papers managed by Passagen
    type: streamable-http
    url: http://passagen-mcp:8766/mcp
    headers:
      Authorization: Bearer ${PASSAGEN_MCP_TOKEN}
    requiresOAuth: false
    timeout: 60000
    initTimeout: 15000
    serverInstructions: true
```

Restart LibreChat after editing `librechat.yaml`. The bearer token must have the same value in the
LibreChat and Passagen MCP containers. Never commit it to either repository.

## Host Deployment

When Passagen MCP runs on the Docker host rather than in the LibreChat network, bind it to a
reachable host address and explicitly allow the address LibreChat sends in the Host header. On
Linux, LibreChat may also need `host.docker.internal:host-gateway` in `extra_hosts`.

Do not expose the plain HTTP endpoint to an untrusted network. Put it behind a TLS reverse proxy and
an appropriate authentication system before remote deployment. The built-in static bearer token is
intended for trusted service-to-service deployments, not as a replacement for user-scoped OAuth.
