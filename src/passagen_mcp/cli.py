from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import uvicorn
from passagen.catalog import CatalogError

from passagen_mcp import __version__
from passagen_mcp.config import ConfigurationError, HttpSettings, LibrarySettings
from passagen_mcp.library import LibraryReader
from passagen_mcp.server import create_http_app, create_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="passagen-mcp", description="Expose a Passagen paper library over MCP"
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    stdio = subparsers.add_parser("stdio", help="serve a local MCP client over standard I/O")
    _library_arguments(stdio)

    serve = subparsers.add_parser("serve", help="serve MCP over Streamable HTTP")
    _library_arguments(serve)
    serve.add_argument("--host", default="127.0.0.1", help="listen address (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8766, help="listen port (default: 8766)")
    serve.add_argument(
        "--token-env",
        default="PASSAGEN_MCP_TOKEN",
        help="environment variable containing the bearer token",
    )
    serve.add_argument(
        "--allow-host",
        action="append",
        default=[],
        help="allow an HTTP Host value for DNS-rebinding protection (repeatable)",
    )
    serve.add_argument(
        "--allow-origin",
        action="append",
        default=[],
        help="allow a browser Origin value (repeatable)",
    )
    return parser


def _library_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data-dir", type=Path, required=True, help="Passagen data directory")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="explicit config file (default: <data-dir>/passagen.yaml)",
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = LibrarySettings.load(args.data_dir, config_path=args.config)
        library = LibraryReader(settings.database_path, settings.data_dir)
        mcp = create_server(library)
        _configure_logging()
        if args.command == "stdio":
            mcp.run(transport="stdio")
            return
        token = os.environ.get(args.token_env)
        http = HttpSettings(
            host=args.host,
            port=args.port,
            token=token,
            allowed_hosts=tuple(args.allow_host),
            allowed_origins=tuple(args.allow_origin),
        )
        application = create_http_app(mcp, http)
    except (ConfigurationError, CatalogError) as exc:
        parser.error(str(exc))
    logging.getLogger("passagen_mcp").info(
        "server_starting host=%s port=%s auth=%s",
        http.host,
        http.port,
        "enabled" if http.token is not None else "disabled",
    )
    uvicorn.run(
        application,
        host=http.host,
        port=http.port,
        log_config=None,
        access_log=False,
    )


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
        force=True,
    )


if __name__ == "__main__":
    main()
