# National Parks Server — local MCP environment

This backend stores National Park entities and the operational content users query: alerts, visitor centers, campgrounds, and events. The main workflow is read-heavy: list parks, fetch a park’s details, and retrieve time-sensitive park-related resources; internally it also tracks API consumers and request logs for rate limiting and observability.

Repository: https://github.com/KyrieTangSheng/mcp-server-nationalparks
Homepage: https://smithery.ai/server/@KyrieTangSheng/mcp-server-nationalparks

## Datastore

- `parks.json` — Canonical national park records used for listing and detailed park views. (30 rows; fields: ['id', 'nps_park_code', 'full_name', 'description', 'state_codes', 'latitude', 'longitude', 'designation', 'url', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'archived']
  - constraint: unique(nps_park_code)
  - constraint: full_name <> ''
  - constraint: json_array_length(state_codes) >= 1
  - constraint: latitude between -90 and 90 when not null
- `park_alerts.json` — Current and historical alerts for parks (closures, hazards, info bulletins). (31 rows; fields: ['id', 'park_id', 'title', 'description', 'category', 'severity', 'effective_start_at', 'effective_end_at', 'source_url', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'cancelled', 'archived']
  - constraint: fk(park_id) references parks(id) on delete cascade
  - constraint: title <> ''
  - constraint: effective_end_at is null or effective_start_at is null or effective_end_at >= effective_start_at
- `visitor_centers.json` — Visitor centers for parks, including seasonal/weekly operating hours stored as structured JSON. (40 rows; fields: ['id', 'park_id', 'name', 'description', 'latitude', 'longitude', 'phone', 'email', 'hours_json', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'closed', 'seasonal', 'archived']
  - constraint: fk(park_id) references parks(id) on delete cascade
  - constraint: unique(park_id, name)
  - constraint: name <> ''
  - constraint: latitude between -90 and 90 when not null
- `campgrounds.json` — Campgrounds and their amenities/availability metadata for parks. (36 rows; fields: ['id', 'park_id', 'name', 'description', 'latitude', 'longitude', 'amenities_json', 'campsites_count', 'reservation_url', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'closed', 'seasonal', 'archived']
  - constraint: fk(park_id) references parks(id) on delete cascade
  - constraint: unique(park_id, name)
  - constraint: name <> ''
  - constraint: campsites_count is null or campsites_count >= 0
- `park_events.json` — Events hosted by parks (talks, ranger programs, tours) with scheduling windows. (34 rows; fields: ['id', 'park_id', 'title', 'description', 'location', 'start_at', 'end_at', 'all_day', 'timezone', 'cost_usd', 'registration_url', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['scheduled', 'cancelled', 'completed', 'archived']
  - constraint: fk(park_id) references parks(id) on delete cascade
  - constraint: title <> ''
  - constraint: end_at is null or start_at is null or end_at >= start_at
  - constraint: cost_usd is null or cost_usd >= 0
- `api_consumers.json` — API consumer identities for request attribution, rate limiting, and analytics. Used even if the public tools do not expose keys directly. (18 rows; fields: ['id', 'name', 'api_key_hash', 'status', 'requests_per_minute_limit', 'created_at', 'updated_at', 'last_seen_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(api_key_hash)
  - constraint: name <> ''
  - constraint: requests_per_minute_limit between 1 and 6000

## Business rules enforced by the tools

- findParks returns parks where parks.status = 'active' ordered by full_name asc; may additionally filter by state_codes/term internally, but no tool parameters are required.
- getParkDetails resolves a single park by parks.id or parks.nps_park_code (implementation choice); returned park must have status in ('active','inactive') or respond not_found for 'archived'.
- getAlerts returns alerts with status='active' and (effective_end_at is null or effective_end_at >= now()); alerts are scoped to a park when a park context is provided by the server/runtime.
- getVisitorCenters returns visitor centers with status in ('open','seasonal'); status='closed' may be included only when explicitly requested by internal callers (not exposed in current tool parameters).
- getCampgrounds returns campgrounds with status in ('open','seasonal'); if amenities_json is present it must be valid JSON object.
- getEvents returns events with status='scheduled' and (start_at is null or start_at >= now() - interval '1 day'); if start_at/end_at are present, end_at must be >= start_at.
- FK integrity is enforced: park_alerts.park_id, visitor_centers.park_id, campgrounds.park_id, park_events.park_id must reference existing parks.id; deleting a park cascades deletes to these child rows.
- Lifecycle transitions must follow the declared transitions maps; direct updates that skip allowed transitions are rejected.
- API access must be attributed to an api_consumers row when an API key is used; requests from consumers with status in ('suspended','revoked') are rejected.
- Rate limiting: a consumer may not exceed api_consumers.requests_per_minute_limit; when exceeded, requests are rejected and last_seen_at is still updated only on accepted requests.