# Kakao Map — local MCP environment

This backend stores Kakao Map place recommendation requests and the resulting recommended places returned by the upstream Kakao Map APIs. The main workflow is: create a recommendation run, call upstream search/ranking logic, persist a ranked list of recommended places, and allow auditing and rate limiting via API keys.

Repository: https://github.com/cgoinglove/mcp-server-kakao-map
Homepage: https://smithery.ai/server/@cgoinglove/mcp-server-kakao-map

## Datastore

- `api_keys.json` — API keys used to authenticate callers of the MCP Kakao Map place recommender, track quotas, and associate usage with an owner. (18 rows; fields: ['id', 'key_hash', 'key_prefix', 'owner_type', 'owner_id', 'status', 'quota_requests_per_day', 'quota_requests_per_minute', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'suspended']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix, owner_type, owner_id)
  - constraint: quota_requests_per_day >= 0
  - constraint: quota_requests_per_minute >= 0
- `recommendation_runs.json` — A single execution of kakao_map_place_recommender. Captures request context (even if empty) and execution status, errors, and timing. (18 rows; fields: ['id', 'api_key_id', 'request_source', 'request_metadata', 'status', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: status in ('queued','running','succeeded','failed','cancelled')
  - constraint: finished_at is null or started_at is not null
  - constraint: finished_at is null or finished_at >= started_at
  - constraint: error_code is null or status = 'failed'
- `places.json` — Normalized place records (typically derived from Kakao Local/Map place search). A place can appear in multiple recommendation runs. (18 rows; fields: ['id', 'provider', 'provider_place_id', 'name', 'category_name', 'phone', 'address_name', 'road_address_name', 'longitude', 'latitude', 'place_url', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'deleted']
  - constraint: unique(provider, provider_place_id)
  - constraint: latitude is null or (latitude >= -90 and latitude <= 90)
  - constraint: longitude is null or (longitude >= -180 and longitude <= 180)
  - constraint: status in ('active','stale','deleted')
- `recommendation_items.json` — Ranked output items for a recommendation run. Each row links a run to a place with ordering and scoring metadata. (18 rows; fields: ['id', 'recommendation_run_id', 'place_id', 'rank', 'score', 'reason', 'raw_provider_payload', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active']
  - constraint: foreign key(recommendation_run_id) references recommendation_runs(id) on delete cascade
  - constraint: foreign key(place_id) references places(id) on delete restrict
  - constraint: unique(recommendation_run_id, rank)
  - constraint: unique(recommendation_run_id, place_id)
- `usage_events.json` — Append-only usage log for quota enforcement and auditing. One run may generate multiple events (e.g., auth, upstream call, completion). (19 rows; fields: ['id', 'api_key_id', 'recommendation_run_id', 'event_type', 'units', 'http_status', 'upstream_status', 'latency_ms', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['request_received', 'quota_checked', 'upstream_called', 'request_succeeded', 'request_failed']
  - constraint: units >= 0
  - constraint: latency_ms is null or latency_ms >= 0
  - constraint: http_status is null or (http_status >= 100 and http_status <= 599)
  - constraint: upstream_status is null or (upstream_status >= 100 and upstream_status <= 599)

## Business rules enforced by the tools

- Invoking kakao_map_place_recommender with an authenticated caller MUST create a recommendation_runs row (status 'queued' then 'running') and at least one usage_events row with event_type='request_received'.
- If api_key_id is present, the service MUST enforce quota_requests_per_minute and quota_requests_per_day based on summed usage_events.units for that api_key_id in the relevant time windows; on violation it MUST set recommendation_runs.status='failed' with error_code='QUOTA_EXCEEDED' and record usage_events.event_type='request_failed'.
- A recommendation_runs row MUST transition status only according to the declared transitions; terminal states ('succeeded','failed','cancelled') MUST NOT change afterward.
- When a run succeeds, it MUST have finished_at set, status='succeeded', and it SHOULD create N recommendation_items with contiguous unique rank values starting at 1.
- Each recommendation_items row MUST reference an existing recommendation_runs row and an existing places row; deleting a recommendation run MUST cascade-delete its recommendation_items.
- places(provider, provider_place_id) MUST be unique; inserting a recommendation item for an existing provider_place_id MUST reuse the existing places row rather than creating a duplicate.
- The tool surface has no explicit parameters; therefore any filtering or personalization MUST be derived from request_metadata and/or api_key owner context, both of which MUST be stored on the recommendation_runs row for auditability.