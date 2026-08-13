# Terraform MCP Server — local MCP environment

This backend indexes Terraform Registry provider documentation and module metadata to support two-step resolution flows: (1) resolve a human query (provider + service slug + doc type) into a concrete providerDocID, then fetch the rendered provider docs; (2) search modules by query with pagination, then fetch module details by an exact moduleID. It also records tool invocations for auditing, debugging, and enforcing simple request limits.

Repository: https://github.com/hashicorp/terraform-mcp-server
Homepage: https://smithery.ai/server/@hashicorp/terraform-mcp-server

## Datastore

- `providers.json` — Terraform provider identities and version catalog used to scope provider documentation resolution. (18 rows; fields: ['id', 'namespace', 'name', 'display_name', 'status', 'latest_version', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: unique(namespace, name)
  - constraint: status in ('active','deprecated','disabled')
  - constraint: latest_version is null or matches semver ^\d+\.\d+\.\d+$
- `provider_docs.json` — Provider documentation pages addressable by a tfprovider-compatible providerDocID; includes doc type, service slug, version and rendered content/metadata. (18 rows; fields: ['id', 'provider_id', 'external_provider_doc_id', 'provider_version', 'provider_data_type', 'service_slug', 'title', 'canonical_path', 'content_markdown', 'content_html', 'content_etag', 'last_fetched_at', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['candidate', 'ready', 'stale', 'error']
  - constraint: foreign key(provider_id) references providers(id) on delete restrict
  - constraint: unique(external_provider_doc_id)
  - constraint: unique(provider_id, provider_version, provider_data_type, service_slug, canonical_path)
  - constraint: provider_version matches semver ^\d+\.\d+\.\d+$
- `modules.json` — Terraform Registry module catalog and cached module documentation/details addressable by exact moduleID used by moduleDetails. (19 rows; fields: ['id', 'module_id', 'namespace', 'name', 'provider', 'version', 'description', 'verified', 'downloads', 'source_url', 'documentation_markdown', 'inputs', 'outputs', 'last_fetched_at', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['indexed', 'stale', 'error']
  - constraint: unique(module_id)
  - constraint: downloads >= 0
  - constraint: version matches semver ^\d+\.\d+\.\d+$
  - constraint: status in ('indexed','stale','error')
- `tool_requests.json` — Audit log of tool invocations and their resolved targets (provider docs/modules), used for debugging, rate limiting, and cache effectiveness tracking. (19 rows; fields: ['id', 'tool_name', 'request_params', 'provider_id', 'provider_doc_id', 'module_id', 'current_offset', 'response_status', 'response_bytes', 'latency_ms', 'created_at', 'updated_at'])
  - lifecycle `response_status`: ['ok', 'not_found', 'invalid_request', 'upstream_error', 'rate_limited']
  - constraint: tool_name in ('resolveProviderDocID','getProviderDocs','searchModules','moduleDetails')
  - constraint: foreign key(provider_id) references providers(id) on delete set null
  - constraint: foreign key(provider_doc_id) references provider_docs(id) on delete set null
  - constraint: foreign key(module_id) references modules(id) on delete set null

## Business rules enforced by the tools

- resolveProviderDocID(providerNamespace, providerName, serviceSlug, providerDataType, providerVersion) must resolve provider_id by exact match on providers(namespace,name); if not found, return not_found and write a tool_requests row with response_status='not_found'.
- If providerVersion is omitted or equals 'latest', the system must use providers.latest_version; if latest_version is null, it must attempt to fetch latest from upstream and then persist providers.latest_version before continuing.
- resolveProviderDocID must search provider_docs by (provider_id, provider_version, provider_data_type) and rank by service_slug similarity to the provided serviceSlug; it returns one or more candidates, each mapping to provider_docs.external_provider_doc_id.
- getProviderDocs(providerDocID) must locate provider_docs by external_provider_doc_id; if found and status in ('ready','stale'), return cached content and, if stale or last_fetched_at older than the refresh TTL, asynchronously refresh and transition status stale->ready on success or stale->error on failure.
- getProviderDocs must not accept any identifier other than the exact external_provider_doc_id string; non-numeric strings are allowed only if present in provider_docs.external_provider_doc_id (do not coerce).
- searchModules(moduleQuery, currentOffset) must query modules by text match over (namespace, name, description) and order results by (verified desc, downloads desc, name asc); currentOffset must be treated as an integer offset and must be >= 0.
- searchModules must enforce a maximum page size (implementation-defined) and must never return duplicate module_id values within a single response.
- moduleDetails(moduleID) must locate modules by modules.module_id; if found and status in ('indexed','stale'), return cached documentation_markdown/inputs/outputs and refresh asynchronously when stale or beyond TTL, transitioning stale->indexed on success or stale->error on failure.
- All tool invocations must create a tool_requests row with tool_name, request_params, and final response_status; successful resolutions should populate the corresponding FK fields (provider_id/provider_doc_id/module_id).
- Foreign key integrity must be enforced: provider_docs.provider_id must reference an existing providers row; tool_requests references may be null but if present must reference existing rows.
- Downloads must be non-negative and should be updated only by trusted upstream sync; direct API calls must not mutate modules.downloads.