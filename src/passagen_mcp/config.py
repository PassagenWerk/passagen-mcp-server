from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from passagen.catalog import CatalogService
from passagen.config import ConfigError, load_settings, resolve_config_path
from passagen.config import Settings as CoreSettings


class ConfigurationError(ValueError):
    """Raised when the MCP server cannot safely open a Passagen library."""


@dataclass(frozen=True, slots=True)
class LibrarySettings:
    data_dir: Path
    core: CoreSettings
    config_path: Path | None

    @property
    def database_path(self) -> Path:
        return self.core.resolved_database_path

    @classmethod
    def load(cls, data_dir: Path, *, config_path: Path | None = None) -> LibrarySettings:
        resolved = data_dir.expanduser().resolve()
        if not resolved.is_dir():
            raise ConfigurationError(f"Passagen data directory does not exist: {resolved}")
        try:
            core = load_settings(config_path, {"data_dir": resolved})
        except ConfigError as exc:
            raise ConfigurationError(str(exc)) from exc
        if not core.resolved_database_path.is_file():
            raise ConfigurationError(
                f"Passagen database does not exist: {core.resolved_database_path}"
            )
        # Constructing the facade performs the canonical schema compatibility check.
        CatalogService(core.resolved_database_path, resolved)
        return cls(resolved, core, resolve_config_path(config_path, resolved))


@dataclass(frozen=True, slots=True)
class HttpSettings:
    host: str = "127.0.0.1"
    port: int = 8766
    token: str | None = field(default=None, repr=False)
    allow_write: bool = False
    allowed_hosts: tuple[str, ...] = ()
    allowed_origins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ConfigurationError("Port must be between 1 and 65535")
        if self.token is not None and not self.token.strip():
            raise ConfigurationError("Bearer token must not be blank")
        if self.allow_write and self.token is None:
            raise ConfigurationError(
                "A bearer token is required when collection writes are enabled"
            )
        if any(not host.strip() or "/" in host for host in self.allowed_hosts):
            raise ConfigurationError("Allowed hosts must be Host header values, not URLs")
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
            ):
                raise ConfigurationError(f"Invalid allowed origin: {origin}")
        if not _is_loopback(self.host):
            if self.token is None:
                raise ConfigurationError("A bearer token is required for non-loopback HTTP")
            if self.host in {"0.0.0.0", "::"} and not self.allowed_hosts:
                raise ConfigurationError("--allow-host is required for a wildcard listen address")

    @property
    def transport_hosts(self) -> list[str]:
        if self.allowed_hosts:
            hosts: list[str] = []
            for value in self.allowed_hosts:
                host = value.strip()
                hosts.append(host)
                if ":" not in host:
                    hosts.append(f"{host}:*")
            return list(dict.fromkeys(hosts))
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        names = [host, f"{host}:{self.port}"]
        if _is_loopback(self.host):
            names.extend(["localhost", f"localhost:{self.port}"])
        return list(dict.fromkeys(names))


def _is_loopback(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
