# Kakao Navigation — local MCP environment

This backend stores Kakao Navigation API access credentials, normalized location entities (addresses/places and their coordinates), and route search jobs (including future-departure and multi-destination requests) with cached responses for auditing, rate-limiting, and replay. Main workflows: (1) geocode/place search to create or reuse location records, (2) create direction search jobs that reference those locations, (3) store provider responses and usage for quota enforcement.

Repository: https://github.com/CaChiJ/kakao-mobility-mcp-server
Homepage: https://smithery.ai/server/@CaChiJ/kakao-mobility-mcp-server

## Datastore

- `api_clients.json` — Represents a tenant/application using the Kakao Mobility MCP server. Holds API keys, quota settings, and lifecycle state. (28 rows; fields: ['id', 'name', 'status', 'kakao_rest_api_key_hash', 'kakao_key_last4', 'quota_requests_per_minute', 'quota_requests_per_day', 'cache_ttl_seconds', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: quota_requests_per_minute between 1 and 6000
  - constraint: quota_requests_per_day between 1 and 1000000
  - constraint: cache_ttl_seconds between 0 and 604800
- `locations.json` — Normalized location records created from geocoding or place/address searches. Stores coordinates and canonicalized address fields used for routing. (34 rows; fields: ['id', 'client_id', 'source', 'query_text', 'place_name', 'road_address', 'jibun_address', 'region_1depth', 'region_2depth', 'region_3depth', 'lat', 'lng', 'provider_place_id', 'confidence', 'status', 'merged_into_location_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'merged', 'deleted']
  - constraint: lat between -90 and 90
  - constraint: lng between -180 and 180
  - constraint: confidence is null or (confidence between 0 and 1)
  - constraint: merged_into_location_id is null unless status = 'merged'
- `route_searches.json` — A direction search job/request (by coordinates or by address), including future-departure and multi-destination variants. References normalized locations and stores request options used for the upstream Kakao navigation API call. (38 rows; fields: ['id', 'client_id', 'type', 'status', 'origin_location_id', 'destination_location_id', 'origin_address_text', 'destination_address_text', 'departure_at', 'route_preference', 'vehicle_type', 'vehicle_options', 'waypoints', 'request_fingerprint', 'provider', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: unique(client_id, request_fingerprint)
  - constraint: type in ('direction_by_coords','direction_by_address','future_direction_by_coords','multi_destination_by_coords')
  - constraint: provider = 'kakao'
  - constraint: departure_at is null unless type = 'future_direction_by_coords'
- `route_search_destinations.json` — Child table for multi-destination direction searches. Stores the list of destination locations and preserves input order. (30 rows; fields: ['id', 'route_search_id', 'destination_location_id', 'seq', 'label', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(route_search_id, seq)
  - constraint: seq between 0 and 999
  - constraint: destination_location_id required
  - constraint: route_search_id must reference a route_searches row with type = 'multi_destination_by_coords'
- `provider_responses.json` — Cached upstream Kakao API responses for geocode/place searches and direction searches. Enables replay, auditing, and reduced upstream calls. (42 rows; fields: ['id', 'client_id', 'entity_type', 'location_id', 'route_search_id', 'provider', 'endpoint', 'request_fingerprint', 'http_status', 'response_json', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'purged']
  - constraint: unique(client_id, entity_type, request_fingerprint)
  - constraint: http_status between 100 and 599
  - constraint: expires_at > created_at
  - constraint: location_id is not null when entity_type in ('location_search','geocode')
- `api_usage_events.json` — Append-only usage ledger for quota enforcement and auditing per tool call. Each MCP tool invocation generates at least one usage event and can be linked to created route searches/locations. (33 rows; fields: ['id', 'client_id', 'tool_name', 'status', 'request_fingerprint', 'location_id', 'route_search_id', 'provider_http_status', 'latency_ms', 'billed_units', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'failed', 'rate_limited']
  - constraint: billed_units between 0 and 100
  - constraint: latency_ms is null or latency_ms between 0 and 600000
  - constraint: provider_http_status is null or provider_http_status between 100 and 599
  - constraint: tool_name in ('direction_search_by_coords','direction_search_by_address','address_search_by_place_name','geocode','future_direction_search_by_coords','multi_destination_direction_search')

## Business rules enforced by the tools

- Every tool call MUST create an api_usage_events row with tool_name equal to the invoked tool and status in (succeeded, failed, rate_limited).
- If api_clients.status != 'active', all tool calls MUST be rejected and recorded as api_usage_events.status='failed' (or 'rate_limited' if enforced that way).
- Per client, requests per minute and per day MUST NOT exceed api_clients.quota_requests_per_minute and api_clients.quota_requests_per_day; when exceeded, the call MUST be rejected and recorded with api_usage_events.status='rate_limited' and billed_units=0.
- address_search_by_place_name and geocode MUST upsert into locations using (client_id, provider_place_id) when provider_place_id is present; otherwise a new locations row MAY be created with source set appropriately.
- direction_search_by_address MUST create (or reuse) locations for origin and destination via geocoding, then create a route_searches row with type='direction_by_address' referencing those locations and storing origin_address_text/destination_address_text.
- direction_search_by_coords MUST create a route_searches row with type='direction_by_coords' and origin_location_id/destination_location_id referencing existing or newly created locations (source='manual' if created from raw coords).
- future_direction_search_by_coords MUST require departure_at in the future (>= now) and create a route_searches row with type='future_direction_by_coords'; if waypoints are provided they MUST reference active locations and be <= 10.
- multi_destination_direction_search MUST create a route_searches row with type='multi_destination_by_coords' and create route_search_destinations rows with contiguous seq starting at 0; at least 2 destinations MUST be present.
- For any upstream Kakao call made, the system MUST store a provider_responses row keyed by (client_id, entity_type, request_fingerprint) and set expires_at = created_at + api_clients.cache_ttl_seconds (unless upstream provides a stricter TTL).
- For cache hits (provider_responses.status='fresh' and expires_at > now), the system SHOULD avoid upstream calls and still record api_usage_events with provider_http_status null (or 304-style internal code) and billed_units=1 unless product policy sets billed_units=0 for cache hits.
- route_searches.status transitions MUST follow the declared lifecycle; once succeeded/failed/cancelled, the row MUST be immutable except updated_at and attaching provider_responses.
- FK integrity MUST be enforced: route_searches.origin_location_id/destination_location_id and route_search_destinations.destination_location_id MUST reference locations.status='active' at execution time; if a location is merged, callers MUST be redirected to merged_into_location_id.