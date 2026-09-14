from __future__ import annotations

from pathlib import Path

import pytest

from passagen_mcp.config import ConfigurationError, HttpSettings, LibrarySettings


def test_library_settings_loads_existing_library(data_dir: Path) -> None:
    settings = LibrarySettings.load(data_dir)

    assert settings.data_dir == data_dir.resolve()
    assert settings.database_path == (data_dir / "passagen.db").resolve()


def test_library_settings_rejects_missing_paths(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="data directory"):
        LibrarySettings.load(tmp_path / "missing")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ConfigurationError, match="database"):
        LibrarySettings.load(empty)


def test_http_settings_validate_and_expand_deployment_hosts() -> None:
    settings = HttpSettings(
        host="0.0.0.0",
        token="secret",
        allowed_hosts=("passagen-mcp",),
        allowed_origins=("https://chat.example.com",),
    )

    assert settings.transport_hosts == ["passagen-mcp", "passagen-mcp:*"]
    with pytest.raises(ConfigurationError, match="not URLs"):
        HttpSettings(allowed_hosts=("http://localhost",))
    with pytest.raises(ConfigurationError, match="Invalid allowed origin"):
        HttpSettings(allowed_origins=("chat.example.com",))
