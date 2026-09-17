# Changelog

All notable changes to Passagen MCP Server are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] - 2026-09-17

Requires `passagen-core` `0.9.x` and Passagen Schema version 13.

### Added

- Added GitLab CI for linting, type checking, tests, coverage reports, tag-version validation, and
  isolated wheel installation.
- Added a Chinese Docker Hub overview and automatic overview synchronization after image pushes.

### Fixed

- Updated Docker Hub overview publishing to the Node 24-compatible description action.

## [0.3.0] - 2026-09-17

Requires `passagen-core` `0.9.x` and Passagen Schema version 13.

### Added

- Added `get_papers` and `resolve_papers` for bounded bulk metadata retrieval and exact resolution
  by ID, normalized title, DOI, or arXiv ID.
- Added opt-in tools to create and update tags, batch-add or remove paper tags with dry-run support,
  and update collection names or descriptions.
- Added per-paper results, partial success, atomic mode, and dry-run support to
  `add_papers_to_collection`.
- Added collection document discovery, retrieval, resources, and idempotent Markdown creation.

### Changed

- Replaced opaque paper cursors with resumable `offset` and `limit` pagination. List responses now
  report `returned`, `total`, `next_offset`, and `has_more` before their items.
- `list_papers` and `get_papers` now support explicit field projections and default to
  `id`, `title`, `year`, and `tags`.
- Added pagination and compact defaults to tags, collections, collection members, and collection
  documents; expensive document paper snapshots and changes are now opt-in.
- Tool failures now use stable error categories such as `not_found`, `validation_error`,
  `conflict`, and `busy`.
- Collection and paper-tag mutations return counts and one status for every requested paper ID.

### Removed

- Removed `cursor` and `page_size` from `list_papers`; callers must use `offset` and `limit`.

## [0.2.0] - 2026-09-15

Requires `passagen-core` `0.8.x` and Passagen Schema version 11.

### Added

- Added opt-in tools to create collections and append existing papers, with write access disabled
  by default and authenticated HTTP required when enabled.
- Added `get_paper_citation` for persisted BibTeX retrieval with provenance, cache state, and
  optional refresh.

### Changed

- Updated shared database compatibility to Passagen Schema version 11.

## [0.1.0] - 2026-09-14

Requires `passagen-core` `0.7.x` and Passagen Schema version 10.

### Added

- Added read-only paper, tag, collection, full-text section, synthesis, and research report tools.
- Added stable paper and collection resource templates with validated content and safe artifact
  metadata that omits managed filesystem paths.
- Added local stdio and authenticated Streamable HTTP transports, health checks, Host/Origin
  protection, and a standalone multi-platform Docker release workflow.
- Documented integration with compatible MCP Agent Hosts and bounded multi-tool research workflows.
