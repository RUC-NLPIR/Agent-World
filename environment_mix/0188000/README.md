# Ref — local MCP environment

This backend stores documentation/search artifacts and URL fetch-to-markdown read results used by the Ref MCP tools. The main workflows are (1) indexing documentation sources into searchable documents and (2) fetching arbitrary URLs, converting them to markdown, and caching the result for subsequent reads and operational auditing.

Repository: https://github.com/ref-tools/ref-tools-mcp
Homepage: https://smithery.ai/server/@ref-tools/ref-tools-mcp

## Datastore

- `workspaces.json` — Tenant/workspace container for documentation sources, indexed docs, and read-url cache. Even if the MCP tools do not expose workspace selection, production services typically run in a default workspace per deployment. (12 rows; fields: ['id', 'slug', 'name', 'status', 'default_locale', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(slug)
  - constraint: slug length between 3 and 64
  - constraint: default_locale matches /^[a-z]{2}(-[A-Z]{2})?$/
- `documentation_sources.json` — Configurable documentation/source targets that are indexed to support ref_search_documentation. Sources may be repos, doc sites, or known doc bundles; indexing jobs populate indexed_documents. (12 rows; fields: ['id', 'workspace_id', 'source_type', 'name', 'base_url', 'repo_url', 'status', 'last_indexed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'paused', 'deleted']
  - constraint: foreign key(workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, name)
  - constraint: if source_type = 'web_docs' then base_url is not null
  - constraint: if source_type = 'git_repo' then repo_url is not null
- `indexed_documents.json` — Searchable documentation documents/sections produced by indexing documentation_sources. This is the primary corpus queried by ref_search_documentation. (19 rows; fields: ['id', 'workspace_id', 'source_id', 'canonical_url', 'title', 'content_markdown', 'content_text', 'language', 'hash_sha256', 'indexed_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded', 'deleted']
  - constraint: foreign key(workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key(source_id) references documentation_sources(id) on delete restrict
  - constraint: unique(workspace_id, canonical_url, hash_sha256)
  - constraint: length(hash_sha256) = 64
- `read_url_requests.json` — Audit trail and cache key for the ref_read_url tool. Each call to read a URL creates a request record and stores whether it was served from cache. (18 rows; fields: ['id', 'workspace_id', 'url', 'normalized_url', 'status', 'http_status', 'error_code', 'error_message', 'served_from_cache', 'cache_entry_id', 'requested_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'fetching', 'converting', 'succeeded', 'failed', 'blocked']
  - constraint: foreign key(workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key(cache_entry_id) references url_content_cache(id) on delete set null
  - constraint: url matches /^https?:\/\//
  - constraint: normalized_url matches /^https?:\/\//
- `url_content_cache.json` — Cache of fetched URL content and its markdown conversion used by ref_read_url. Entries are keyed by normalized URL and a fetch fingerprint (headers/content-type) to safely reuse results. (19 rows; fields: ['id', 'workspace_id', 'normalized_url', 'final_url', 'content_type', 'etag', 'last_modified', 'fetched_at', 'expires_at', 'status', 'http_status', 'raw_body_sha256', 'markdown', 'text', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'purged']
  - constraint: foreign key(workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, normalized_url, raw_body_sha256)
  - constraint: normalized_url matches /^https?:\/\//
  - constraint: http_status between 100 and 599 when not null

## Business rules enforced by the tools

- ref_search_documentation must query indexed_documents where status = 'active' and the parent documentation_sources.status = 'active' for the caller's workspace; results returned to clients must include canonical_url so they can be passed to ref_read_url.
- If no documentation sources exist for a workspace, ref_search_documentation returns an empty result set rather than erroring; operators must create at least one documentation_sources row for meaningful results.
- ref_read_url must create a read_url_requests row for every invocation with requested_at set and status starting at 'queued' or directly 'fetching'.
- Before fetching, ref_read_url must canonicalize the input into normalized_url (strip fragment, normalize scheme/host casing, resolve default ports) and attempt to reuse a non-expired url_content_cache entry with status in ('fresh') for the same workspace; if used, served_from_cache=true and status becomes 'succeeded' without network IO.
- A url_content_cache entry may only be marked 'fresh' if markdown is non-empty and fetched_at is set; purged entries must not be served.
- For safety, ref_read_url must block URLs matching private network ranges (e.g., 127.0.0.0/8, 10.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, ::1, fc00::/7) and record read_url_requests.status='blocked' with error_code='ssrf_blocked'.
- If upstream fetch fails or conversion fails, ref_read_url must set read_url_requests.status='failed', set error_code, set completed_at, and must not create a 'fresh' cache entry.
- FK integrity: documentation_sources.workspace_id must equal indexed_documents.workspace_id for all rows (enforced by application-level check on insert/update).
- Quota/abuse control: per workspace, ref_read_url must enforce a maximum of 60 requests per minute (rate-limited at application level) and should refuse additional calls with status='failed' and error_code='rate_limited' while still recording the attempt.