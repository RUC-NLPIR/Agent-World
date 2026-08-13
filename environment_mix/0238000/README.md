# OpenAPI MCP Server — local MCP environment

This backend stores OpenAPI specification sources (either a known catalog ID or a direct URL), normalized metadata extracted from those specs, and the operations (endpoints) within each spec. The main workflow is: resolve an API identifier to a canonical spec source, fetch/parse it into an overview, and then look up a specific operation by operationId or route path.

Repository: https://github.com/janwilmake/openapi-mcp-server
Homepage: https://smithery.ai/server/@janwilmake/openapi-mcp-server

## Datastore

- `api_specs.json` — Canonical OpenAPI spec sources and their fetch/parse lifecycle. One row represents one resolvable API identifier (catalog ID or URL) and its latest parsed representation. (27 rows; fields: ['id', 'external_id', 'source_url', 'source_kind', 'resolved_canonical_id', 'content_type', 'http_etag', 'http_last_modified', 'last_fetched_at', 'last_parsed_at', 'parse_error', 'spec_sha256', 'openapi_version', 'spec_format', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['new', 'fetching', 'ready', 'error', 'disabled']
  - constraint: required(resolved_canonical_id, source_kind, status, created_at, updated_at)
  - constraint: exactly_one_of(external_id, source_url) is non-null
  - constraint: unique(resolved_canonical_id)
  - constraint: unique(external_id) where external_id is not null
- `api_overviews.json` — Normalized overview data extracted from an OpenAPI spec for fast serving via getApiOverview. (27 rows; fields: ['id', 'api_spec_id', 'title', 'version', 'description', 'terms_of_service', 'contact', 'license', 'servers', 'tags', 'operation_count', 'security_schemes', 'raw_info', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'error']
  - constraint: required(api_spec_id, title, operation_count, status, created_at, updated_at)
  - constraint: unique(api_spec_id)
  - constraint: operation_count >= 0
  - constraint: fk(api_spec_id) references api_specs(id) on delete cascade
- `api_operations.json` — Operations (endpoints) parsed from an OpenAPI spec, addressable by operationId and/or route path for getApiOperation. (39 rows; fields: ['id', 'api_spec_id', 'method', 'path', 'operation_id', 'summary', 'description', 'tags', 'deprecated', 'parameters', 'request_body', 'responses', 'security', 'route_key', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'removed']
  - constraint: required(api_spec_id, method, path, route_key, deprecated, status, created_at, updated_at)
  - constraint: fk(api_spec_id) references api_specs(id) on delete cascade
  - constraint: unique(api_spec_id, route_key)
  - constraint: unique(api_spec_id, operation_id) where operation_id is not null
- `api_resolutions.json` — Tracks how incoming tool parameter 'id' is resolved (catalog ID vs URL), normalization, and caching decisions. Supports consistent behavior and debugging. (31 rows; fields: ['id', 'input_id', 'normalized_input', 'detected_kind', 'api_spec_id', 'resolved', 'resolution_error', 'created_at', 'updated_at'])
  - lifecycle `detected_kind`: ['catalog_id', 'url', 'unknown']
  - constraint: required(input_id, normalized_input, detected_kind, resolved, created_at, updated_at)
  - constraint: fk(api_spec_id) references api_specs(id) on delete set null
  - constraint: unique(normalized_input) where resolved = true and api_spec_id is not null

## Business rules enforced by the tools

- Tool getApiOverview(id) must resolve id via api_resolutions: if id parses as URL, detected_kind='url'; else 'catalog_id' unless unknown.
- If a resolution yields a new canonical key not present in api_specs, the system must create an api_specs row with status='new' and then transition to 'fetching' to retrieve and parse the spec.
- api_specs.status must be 'ready' before serving overview/operation details from api_overviews/api_operations; otherwise the tool returns an error or triggers a refresh and returns a non-ready response depending on service policy.
- getApiOverview(id) reads api_overviews by api_spec_id; it must return the latest active/stale overview tied to the resolved api_spec_id, with operation_count consistent with the number of non-removed api_operations for that api_spec_id.
- getApiOperation(id, operationIdOrRoute) must locate the api_spec_id via the same resolution path as getApiOverview, then fetch exactly one operation either by (api_spec_id, operation_id) match or by (api_spec_id, route_key) match; if multiple matches exist due to malformed specs, the system must prefer operation_id match over route match and otherwise fail with an ambiguity error.
- operationIdOrRoute matching must accept either an exact operation_id or a route expression; for route expressions without a method, the system must attempt to match any method for the given path and fail if multiple methods exist for that path.
- When a spec is re-fetched and spec_sha256 changes, existing api_overviews/api_operations for that api_spec_id must be marked 'stale' and replaced/updated atomically; operations no longer present must transition to status='removed'.
- A URL-based spec source must be validated to be http/https and must be rejected or marked error if it exceeds configured size limits or fetch is disallowed by policy; such failures must set api_specs.status='error' and populate parse_error/resolution_error appropriately.