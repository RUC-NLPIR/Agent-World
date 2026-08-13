# Context7 — local MCP environment

Context7 stores a catalog of software libraries (mapped to Context7-compatible IDs like '/org/project[/version]') and a continuously refreshed set of documentation sources for each library. Primary workflows are (1) resolving a free-text library name into one or more matching library IDs and (2) fetching focused, token-limited documentation extracts for a specific library ID and optional topic, backed by indexed doc chunks.

Repository: https://github.com/upstash/context7-mcp
Homepage: https://smithery.ai/server/@upstash/context7-mcp

## Datastore

- `libraries.json` — Canonical library records addressable by Context7-compatible IDs. Used by resolve-library-id and as the parent entity for documentation sources, versions and doc chunks. (17 rows; fields: ['id', 'org', 'project', 'default_version', 'canonical_library_id', 'display_name', 'description', 'homepage_url', 'keywords', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'blocked']
  - constraint: unique(canonical_library_id)
  - constraint: canonical_library_id LIKE '/%/%' AND canonical_library_id NOT LIKE '%/%/%' (no version)
  - constraint: org <> '' AND project <> ''
  - constraint: display_name <> ''
- `library_aliases.json` — Searchable aliases and package names mapped to a canonical library. Powers resolve-library-id using exact and fuzzy matching over alias_text. (18 rows; fields: ['id', 'library_id', 'alias_text', 'alias_type', 'source', 'popularity_score', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: unique(library_id, alias_text)
  - constraint: alias_text = lower(trim(alias_text))
  - constraint: popularity_score >= 0
- `library_versions.json` — Known versions for a library. Allows get-library-docs to resolve '/org/project/version' and to pin docs to a versioned snapshot. (17 rows; fields: ['id', 'library_id', 'version', 'context7_compatible_library_id', 'is_default', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(library_id, version)
  - constraint: unique(context7_compatible_library_id)
  - constraint: context7_compatible_library_id LIKE '/%/%/%' (must include version)
  - constraint: version <> ''
- `doc_sources.json` — Defines documentation sources (websites, repos) for each library/version and tracks ingestion/indexing state. (18 rows; fields: ['id', 'library_id', 'library_version_id', 'source_type', 'base_url', 'ingest_status', 'last_ingested_at', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `ingest_status`: ['pending', 'running', 'ready', 'failed', 'disabled']
  - constraint: unique(library_id, library_version_id, base_url)
  - constraint: base_url LIKE 'http%'
  - constraint: library_version_id must reference a library_versions row with same library_id when not null (composite FK integrity rule)
- `doc_chunks.json` — Indexed, retrievable documentation chunks. get-library-docs selects chunks for a given library ID (optionally versioned) and topic, then returns content up to a token budget. (18 rows; fields: ['id', 'doc_source_id', 'library_id', 'library_version_id', 'url', 'title', 'topic_labels', 'content', 'token_count', 'embedding', 'chunk_order', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'deleted']
  - constraint: fk(doc_source_id) references doc_sources(id) on delete cascade
  - constraint: library_id must match doc_sources.library_id for doc_source_id (integrity rule)
  - constraint: library_version_id must match doc_sources.library_version_id for doc_source_id (integrity rule, allowing both null)
  - constraint: unique(doc_source_id, url, chunk_order)

## Business rules enforced by the tools

- resolve-library-id(libraryName) must search libraries.display_name and library_aliases.alias_text (normalized to lower/trim) and return only libraries with status='active' unless explicitly configured to include deprecated.
- resolve-library-id results must be ranked primarily by alias exact match, then by library_aliases.popularity_score, then by libraries.display_name similarity.
- get-library-docs(context7CompatibleLibraryID, topic?, tokens?) must accept IDs in the form '/org/project' or '/org/project/version' and must map them to libraries.canonical_library_id or library_versions.context7_compatible_library_id respectively; otherwise return a not-found error.
- If get-library-docs is called with an unversioned ID ('/org/project'), the backend must select docs from (a) the library_versions row where is_default=true if it exists, else (b) doc_sources/doc_chunks where library_version_id is null.
- get-library-docs must only serve documentation from doc_sources with ingest_status='ready' and doc_chunks with status='active'.
- If topic is provided, get-library-docs must filter or rank doc_chunks by topic_labels containing the topic and/or semantic similarity; topic must not expand the result set beyond the library/version boundary.
- tokens defaults to 10000 when omitted; tokens must be within [1, 100000]. The response must include content whose summed doc_chunks.token_count is <= tokens (or best-effort under the cap).
- A library_versions row with is_default=true must be unique per library_id; changing the default must be an atomic operation that unsets the previous default.
- doc_sources.library_version_id, when set, must reference a version belonging to the same library_id; inserts/updates violating this must be rejected.
- Deleting or disabling a doc_source must prevent its doc_chunks from being returned by get-library-docs (enforced by ingest_status and/or cascading delete).