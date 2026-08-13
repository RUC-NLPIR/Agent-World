# GeoPal Travel and Logistics Server — local MCP environment

GeoPal stores workspaces and API access, plus a history of geospatial operations executed against external providers (e.g., OpenRouteService): geocoding, directions, isochrones, POI search, and route optimizations (VRP/TSP). The main workflow is: an API key authenticates a request, the request is persisted as an operation with inputs, provider call metadata, output summary and raw payload, and usage is metered for quotas/billing.

Repository: https://github.com/Raghu6798/GeoPal_Traveling_and_Logistics
Homepage: https://smithery.ai/server/@Raghu6798/geopal_traveling_and_logistics

## Datastore

- `workspaces.json` — Tenant container for users/teams using GeoPal. Holds plan and quota configuration used to meter and limit geospatial operations. (12 rows; fields: ['id', 'name', 'status', 'plan', 'monthly_op_limit', 'monthly_provider_cost_usd_limit', 'provider_default', 'provider_account_ref', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: monthly_op_limit >= 0
  - constraint: monthly_provider_cost_usd_limit >= 0
- `api_keys.json` — API keys used by clients to call GeoPal tools. Keys are scoped to a workspace and can be disabled/rotated. (19 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'key_prefix', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: length(key_prefix) >= 6
- `geo_operations.json` — Immutable log of each tool execution request/response (geocode, directions, isochrones, POIs, and optimizations). Stores normalized inputs and provider call metadata; raw provider payloads are stored in a separate collection. (20 rows; fields: ['id', 'workspace_id', 'api_key_id', 'tool_name', 'status', 'provider', 'provider_endpoint', 'requested_at', 'started_at', 'finished_at', 'latency_ms', 'error_code', 'error_message', 'request_ip', 'idempotency_key', 'input_text', 'input_coordinates', 'input_locations', 'input_profile', 'input_range', 'input_buffer_m', 'input_limit', 'input_filters', 'input_jobs', 'input_vehicles', 'input_depot_location', 'input_delivery_locations', 'input_start_location', 'input_end_location', 'result_summary', 'provider_http_status', 'provider_request_id', 'estimated_cost_usd', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key (workspace_id) references workspaces(id)
  - constraint: foreign key (api_key_id) references api_keys(id)
  - constraint: estimated_cost_usd >= 0
  - constraint: latency_ms is null or latency_ms >= 0
- `provider_payloads.json` — Stores raw request/response JSON payloads exchanged with the external provider for reproducibility, debugging, and audits. Separated to keep the geo_operations table small and fast. (18 rows; fields: ['id', 'operation_id', 'kind', 'content_type', 'payload_json', 'redaction_level', 'created_at', 'updated_at'])
  - lifecycle `kind`: ['request', 'response']
  - constraint: foreign key (operation_id) references geo_operations(id) on delete cascade
  - constraint: unique(operation_id, kind)
  - constraint: content_type in ('application/json','text/plain')
- `usage_ledger.json` — Append-only metering records used for quota enforcement and monthly reporting per workspace. Typically one record per operation, but can support adjustments/credits. (20 rows; fields: ['id', 'workspace_id', 'api_key_id', 'operation_id', 'tool_name', 'status', 'op_count', 'provider_cost_usd', 'occurred_at', 'month_bucket', 'created_at', 'updated_at'])
  - lifecycle `status`: ['posted', 'voided']
  - constraint: foreign key (workspace_id) references workspaces(id)
  - constraint: foreign key (api_key_id) references api_keys(id)
  - constraint: foreign key (operation_id) references geo_operations(id)
  - constraint: unique(operation_id) where operation_id is not null

## Business rules enforced by the tools

- Every tool invocation must create exactly one geo_operations row with tool_name equal to the tool called; inputs must be recorded in the corresponding input_* fields (e.g., geocode_address -> input_text; get_pois/get_poi_names -> input_coordinates; get_isochrones -> input_locations + input_range + input_profile; optimize_vehicle_routes -> input_jobs + input_vehicles; create_simple_delivery_problem -> input_depot_location + input_delivery_locations; optimize_traveling_salesman -> input_locations, and optionally input_start_location/input_end_location).
- Operations must follow valid status transitions: queued -> running|cancelled; running -> succeeded|failed|cancelled; terminal states cannot transition.
- For get_pois and get_poi_names, input_buffer_m must not exceed 2000 and input_limit must not exceed 500 (get_poi_names should default to <= 10 at the service layer even if input_limit is null).
- For any request authenticated by an active api_keys record, the api_keys.workspace_id must match geo_operations.workspace_id; revoked keys must be rejected before creating a succeeded operation.
- On operation completion (succeeded or failed), a usage_ledger entry must be posted exactly once per operation_id, with op_count = 1 and provider_cost_usd = geo_operations.estimated_cost_usd; adjustments must use tool_name='adjustment' and may have negative values.
- Workspace quota enforcement: for a given workspace and month_bucket, sum(usage_ledger.op_count) where status='posted' must not exceed workspaces.monthly_op_limit; sum(provider_cost_usd) where status='posted' must not exceed workspaces.monthly_provider_cost_usd_limit (hard limit for free/pro; configurable enforcement for enterprise).
- Idempotency: when idempotency_key is provided, repeated requests with the same (workspace_id, tool_name, idempotency_key) must return the existing geo_operations result (and must not create additional usage_ledger rows).
- Raw provider payload storage: provider_payloads must store at most one 'request' and one 'response' per operation, and must redact secrets according to redaction_level before persistence.
- Coordinate validation: any coordinate array must be exactly [lon, lat] with lon in [-180, 180] and lat in [-90, 90]; any input_locations/input_delivery_locations must contain at least 1 location and no more than a plan-specific maximum (e.g., free<=50, pro<=200, enterprise<=2000).