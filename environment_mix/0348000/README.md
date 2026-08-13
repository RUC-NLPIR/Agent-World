# Rust Docs Server — local MCP environment

This backend indexes Rust crates, their published versions, and the documentation artifacts (rustdoc pages, extracted symbol metadata, and vendored source files) needed to serve search and lookup APIs. Core workflows are: ingest/refresh crate version metadata, fetch/build/store docs+source for a specific crate version, and answer end-user queries for crates, symbols, type pages, feature flags, versions, and source files.

Repository: https://github.com/laptou/rust-docs-mcp-server
Homepage: https://smithery.ai/server/@laptou/rust-docs-mcp-server

## Datastore

- `crates.json` — Canonical crate registry entries (name-level). Used to power crate search and to anchor versions, docs, symbols, and files. (17 rows; fields: ['id', 'name', 'description', 'repository_url', 'homepage_url', 'documentation_url', 'downloads_total', 'latest_version', 'last_indexed_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(name)
  - constraint: length(name) >= 1
  - constraint: downloads_total >= 0
  - constraint: latest_version is null OR exists(crate_versions where crate_id = crates.id and version = crates.latest_version)
- `crate_versions.json` — Published versions of a crate and their ingestion/build state. Used by get_crate_versions, version resolution for docs/source/symbol search, and feature flag retrieval. (18 rows; fields: ['id', 'crate_id', 'version', 'yanked', 'published_at', 'rust_version', 'checksum', 'features', 'doc_base_url', 'status', 'last_error', 'indexed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'indexing', 'indexed', 'failed', 'disabled']
  - constraint: unique(crate_id, version)
  - constraint: length(version) >= 1
  - constraint: features is not null
  - constraint: status = 'indexed' implies indexed_at is not null
- `doc_pages.json` — Materialized rustdoc HTML pages (or extracted/normalized page payloads) keyed by crate version and rustdoc path. Used by get_crate_documentation and get_type_info. (18 rows; fields: ['id', 'crate_version_id', 'path', 'page_kind', 'title', 'html', 'content_sha256', 'fetched_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['present', 'missing', 'stale']
  - constraint: unique(crate_version_id, path)
  - constraint: length(path) >= 1
  - constraint: length(html) >= 1
  - constraint: length(content_sha256) = 64
- `source_files.json` — Vendored source code files for a crate version. Used by get_source_code; also supports linking from rustdoc source pages. (17 rows; fields: ['id', 'crate_version_id', 'path', 'language', 'content', 'content_sha256', 'size_bytes', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['present', 'missing']
  - constraint: unique(crate_version_id, path)
  - constraint: length(path) >= 1
  - constraint: size_bytes >= 0
  - constraint: length(content_sha256) = 64
- `symbols.json` — Searchable symbol index per crate version (types, fns, traits, modules, etc.). Used by search_symbols and can support get_type_info lookups by path/name. (18 rows; fields: ['id', 'crate_version_id', 'name', 'kind', 'module_path', 'doc_path', 'signature', 'summary', 'search_text', 'deprecated', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: index(full_text, search_text)
  - constraint: unique(crate_version_id, kind, doc_path, name)
  - constraint: length(name) >= 1
  - constraint: length(doc_path) >= 1

## Business rules enforced by the tools

- Version resolution: if a tool parameter 'version' is omitted, the service must resolve to crates.latest_version; if latest_version is null, return not found.
- get_crate_versions(crateName) returns all crate_versions for the resolved crate, ordered by published_at desc then version desc; must include yanked versions but may optionally filter disabled status at API layer.
- get_feature_flags(crateName, version?) reads crate_versions.features for the resolved crate version; features must be an object mapping strings to arrays of strings.
- get_crate_documentation(crateName, version?) returns the crate root documentation page: prefer doc_pages where path in ("index.html", "{crateName}/index.html") and status='present'; if none exists and crate_versions.status!='indexed', return an indexing/unavailable error.
- get_type_info(crateName, path, version?) must read doc_pages by (crate_version_id, path). If not present, attempt a lazy fetch/build is only allowed when crate_versions.status in ('available','indexed'); on success set doc_pages.status='present' and update fetched_at; on failure set doc_pages.status='missing'.
- get_source_code(crateName, path, version?) must read source_files by (crate_version_id, path). If not present, return not found; if present but status='missing', return not found.
- search_crates(query, page?, perPage?) searches crates.name and crates.description (and optionally repository_url) with status='active'. Pagination defaults: page=1, perPage=10; enforce 1 <= page and 1 <= perPage <= 100.
- search_symbols(crateName, query, version?) searches symbols.search_text for the resolved crate version, with symbols.status='active'. Enforce 1 <= perPage <= 100 (server-defined) and return results ordered by text relevance, then name.
- FK integrity: deleting a crate must be restricted if crate_versions exist; deleting a crate_version must be restricted if doc_pages/source_files/symbols exist (or must cascade as an explicit maintenance operation).
- Indexing lifecycle: setting crate_versions.status to 'indexed' is only valid if at least one doc_pages row with status='present' exists for that crate_version_id and symbols count > 0 (unless crate is empty), and indexed_at is set.
- Paths must be normalized: doc_pages.path and source_files.path must not begin with a leading slash and must not contain '..' segments; writes that violate this must be rejected.