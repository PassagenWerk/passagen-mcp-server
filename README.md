# Passagen MCP Server

Passagen MCP Server exposes a Passagen paper library to MCP-compatible agents. It is read-only
and supports both local stdio clients and deployed Streamable HTTP clients such as LibreChat.

## Features

- Filter and paginate papers by title, status, tags, venue, year, and collection.
- Read validated abstracts, Structured Summary JSON, outlines, and notes.
- Search bounded full-text sections with source pages and artifact hashes.
- Browse tags and ordered collections without exposing managed filesystem paths.
- Read stable `passagen://` resource templates.
- Serve local clients over stdio or remote clients over authenticated Streamable HTTP.

## Install

Clone `passagen-core` and this repository next to each other, then install with uv:

```bash
uv sync --frozen
```

The server reads an existing Passagen data directory. It does not initialize or migrate a library.

## Run

For a local MCP host:

```bash
uv run passagen-mcp stdio --data-dir ../passagen-cli/data
```

For Streamable HTTP on localhost:

```bash
uv run passagen-mcp serve --data-dir ../passagen-cli/data
```

Clients connect to `http://127.0.0.1:8766/mcp`. Localhost may run without authentication. Any
non-loopback listen address requires a bearer token, and wildcard addresses require an explicit
Host allowlist:

```bash
export PASSAGEN_MCP_TOKEN="$(openssl rand -hex 32)"
uv run passagen-mcp serve \
  --data-dir ../passagen-cli/data \
  --host 0.0.0.0 \
  --allow-host passagen-mcp
```

See [LibreChat deployment](docs/librechat.md) for Docker networking and configuration.

## MCP Interface

Tools:

- `list_papers`
- `get_paper_context`
- `search_paper_sections`
- `list_collections`
- `list_tags`

Resource templates:

```text
passagen://papers/{paper_id}
passagen://papers/{paper_id}/abstract
passagen://papers/{paper_id}/summary
passagen://papers/{paper_id}/outline
passagen://papers/{paper_id}/sections/{ordinal}
passagen://collections/{collection_id}
```

`title_query` searches paper titles only. `search_paper_sections` performs bounded English lexical
search over extracted full-text artifacts and does not modify the library.

## Development

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run basedpyright
uv run pytest
```

## License

[GNU Affero General Public License v3.0](LICENSE), SPDX identifier `AGPL-3.0-only`.
