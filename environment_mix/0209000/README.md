# DocsFetcher — local MCP environment

DocsFetcher resolves a library identifier (URL or package name + language) to documentation sources, fetches and normalizes doc content, and returns it to callers. The backend stores libraries/packages, discovered documentation sources, and fetch jobs with produced document snapshots, enabling caching, retries, and multi-language resolution.

Repository: https://github.com/cdugo/mcp-get-docs
Homepage: https://smithery.ai/server/@cdugo/mcp-get-docs

## Datastore

- `libraries.json` — Canonical library/package identity independent of language and any specific documentation URL. Used to group documentation sources and fetch requests for the same logical library. (18 rows; fields: ['id', 'canonical_name', 'name_aliases', 'homepage_url', 'default_language', 'status', 'merged_into_library_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'blocked', 'merged']
  - constraint: unique(lower(canonical_name))
  - constraint: status = 'merged' implies merged_into_library_id is not null
  - constraint: merged_into_library_id != id
  - constraint: homepage_url is null or homepage_url matches URI format
- `package_identifiers.json` — Language/ecosystem-specific package identifiers for a library (e.g., npm react, pypi requests, maven group:artifact). Used by fetch-package-docs and fetch-multilingual-docs. (18 rows; fields: ['id', 'library_id', 'language', 'package_name', 'registry', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'blocked']
  - constraint: unique(library_id, lower(language), lower(package_name))
  - constraint: length(language) between 2 and 32
  - constraint: length(package_name) between 1 and 256
- `doc_sources.json` — Documentation sources (URLs) discovered or provided by the user for a library. A library can have multiple sources per language (API reference, guides, versioned docs). (19 rows; fields: ['id', 'library_id', 'language', 'source_type', 'url', 'url_normalized_hash', 'is_primary', 'last_http_status', 'last_fetched_at', 'etag', 'last_modified', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'unreachable', 'blocked']
  - constraint: unique(url_normalized_hash)
  - constraint: unique(library_id, coalesce(lower(language), ''), is_primary) where is_primary = true
  - constraint: url matches URI format
  - constraint: last_http_status is null or (last_http_status >= 100 and last_http_status <= 599)
- `fetch_jobs.json` — A request to fetch documentation for a URL, package+language, library input, or multiple languages. Used for caching, rate limiting, retries, and observability across all tools. (19 rows; fields: ['id', 'request_type', 'input_url', 'input_library', 'input_package_name', 'input_language', 'input_languages', 'resolved_library_id', 'resolved_source_id', 'cache_key', 'status', 'attempt_count', 'max_attempts', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: unique(cache_key) where status in ('queued','running','succeeded')
  - constraint: attempt_count >= 0
  - constraint: max_attempts between 1 and 10
  - constraint: attempt_count <= max_attempts
- `doc_snapshots.json` — Materialized, normalized documentation content produced by a fetch job for a specific doc source. Acts as the cached response payload backing the tools. (19 rows; fields: ['id', 'job_id', 'source_id', 'library_id', 'language', 'content_format', 'title', 'content', 'content_sha256', 'bytes', 'http_status', 'fetched_url', 'retrieved_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['current', 'stale', 'deleted']
  - constraint: unique(source_id, content_sha256)
  - constraint: unique(job_id, source_id)
  - constraint: bytes >= 0
  - constraint: bytes <= 10485760

## Business rules enforced by the tools

- fetch-url-docs(url): normalize url, upsert a libraries record (canonical_name derived from host/path when unknown), upsert a doc_sources row with source_type='user_url' and url_normalized_hash, then create or reuse a fetch_jobs row with request_type='fetch_url_docs' and cache_key based on normalized url; on success, persist a doc_snapshots row and mark it current while older snapshots for the same source_id become stale.
- fetch-package-docs(packageName, language?): resolve (packageName, language or library.default_language) to a package_identifiers row with status='active'; if not found, create a fetch_jobs row with status='failed' and error_code='RESOLUTION_FAILED'. If found, choose an active doc_sources row (is_primary=true for that library+language if available) or create one with source_type='package_resolved' when the resolver discovers a URL.
- fetch-library-docs(library, language?): if library parses as a valid URI, treat it like fetch-url-docs; otherwise resolve it to libraries.canonical_name or package_identifiers.package_name (optionally constrained by language). Ambiguous resolutions must produce a failed job with error_code='RESOLUTION_FAILED'.
- fetch-multilingual-docs(packageName, languages[]): for each language value, attempt resolution to an active package_identifiers row; create one fetch_jobs row of request_type='fetch_multilingual_docs' that fans out internally; responses are composed from the newest doc_snapshots per (library_id, language) where available; languages array must be non-empty and contain no duplicates after case-folding.
- Blocked entities are not fetchable: if libraries.status='blocked' or doc_sources.status='blocked', any new fetch_jobs must fail with error_code='BLOCKED_SOURCE' before performing network I/O.
- Caching/deduplication: if a fetch_jobs row with the same cache_key is in status queued|running|succeeded and has a current doc_snapshot newer than a configured TTL (e.g., 24h), the tools should return that snapshot without creating a new job.
- Integrity: doc_snapshots.library_id must match doc_sources.library_id; job_id must reference a succeeded fetch_jobs row when inserting a doc_snapshot; deleting a library is disallowed if referenced by active doc_sources or any doc_snapshots (soft-delete via status transitions instead).
- Primary source invariant: at most one doc_sources row can have is_primary=true for a given (library_id, language) pair; setting a source to primary must unset any existing primary within the same pair in the same transaction.