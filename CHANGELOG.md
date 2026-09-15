# Changelog

All notable changes to Passagen MCP Server are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
