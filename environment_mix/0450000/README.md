# TripAdvisor Vacation Planner — local MCP environment

This backend supports a TripAdvisor-style vacation planning API: users search and browse locations, fetch location details, and generate/save vacation plans. It stores a normalized catalog of locations with geo attributes, a search/nearby query log for observability and rate control, and persisted vacation plans with itinerary items referencing locations.

Repository: https://github.com/Ruqyai/tripadvisor-mcp-server
Homepage: https://smithery.ai/server/@Ruqyai/tripadvisor-mcp-server

## Datastore

- `api_keys.json` — API credentials used to access the service, including rate-limit and lifecycle state needed to safely run search, nearby, details, and planning tools. (17 rows; fields: ['id', 'key_hash', 'label', 'status', 'daily_request_limit', 'daily_requests_used', 'usage_window_start', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: daily_request_limit > 0
  - constraint: daily_requests_used >= 0
  - constraint: usage_window_start <= now()
- `locations.json` — Canonical location catalog indexed by TripAdvisor location_id, including geo coordinates, category, and essential display fields used by search, nearby queries, and details lookups. (18 rows; fields: ['id', 'tripadvisor_location_id', 'name', 'category', 'latitude', 'longitude', 'address', 'city', 'region', 'country', 'rating', 'num_reviews', 'price_level', 'url', 'status', 'last_refreshed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'disabled']
  - constraint: unique(tripadvisor_location_id)
  - constraint: latitude is null or (latitude >= -90 and latitude <= 90)
  - constraint: longitude is null or (longitude >= -180 and longitude <= 180)
  - constraint: rating is null or (rating >= 0 and rating <= 5)
- `location_search_requests.json` — Immutable audit/log of user-facing lookup actions for search_locations, get_nearby_locations, and get_location_details_tool. Used for analytics, caching decisions, and enforcing per-key quotas. (18 rows; fields: ['id', 'api_key_id', 'tool_name', 'latitude', 'longitude', 'category', 'location_id', 'status', 'error_code', 'error_message', 'response_count', 'latency_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'succeeded', 'failed', 'rate_limited']
  - constraint: fk(api_key_id) references api_keys(id)
  - constraint: latitude is null or (latitude >= -90 and latitude <= 90)
  - constraint: longitude is null or (longitude >= -180 and longitude <= 180)
  - constraint: response_count is null or response_count >= 0
- `vacation_plans.json` — Top-level vacation planning jobs/sessions started by plan_vacation. Stores the generated plan text/structure and its lifecycle. (18 rows; fields: ['id', 'api_key_id', 'status', 'user_prompt', 'plan_title', 'start_date', 'end_date', 'destination_query', 'generated_plan_text', 'generated_plan_json', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'planning', 'ready', 'cancelled', 'failed']
  - constraint: fk(api_key_id) references api_keys(id)
  - constraint: end_date is null or start_date is null or end_date >= start_date
  - constraint: status != 'failed' or error_code is not null
- `vacation_plan_items.json` — Child rows for a vacation plan, referencing recommended locations (hotels/restaurants/attractions) and scheduling/order details. (17 rows; fields: ['id', 'vacation_plan_id', 'day_index', 'sequence', 'item_type', 'location_id', 'title', 'starts_at', 'ends_at', 'notes', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['proposed', 'confirmed', 'removed']
  - constraint: fk(vacation_plan_id) references vacation_plans(id) on delete cascade
  - constraint: fk(location_id) references locations(id)
  - constraint: sequence >= 1
  - constraint: day_index is null or day_index >= 1

## Business rules enforced by the tools

- Every tool invocation must be logged in location_search_requests with tool_name set appropriately and status transitioned from received to a terminal state (succeeded/failed/rate_limited).
- get_nearby_locations must require latitude and longitude in the request log row; category may be null or one of the allowed enums.
- get_location_details_tool must require a non-null location_id (TripAdvisor upstream ID) in the request log row; if a matching locations.tripadvisor_location_id exists, implementations should upsert/refresh that locations row and set last_refreshed_at.
- search_locations must return results sourced from locations; if the upstream provider is queried, results must be upserted into locations with unique(tripadvisor_location_id) enforced.
- plan_vacation must create a vacation_plans row with status planning (or draft then planning) and must also write a corresponding location_search_requests log row with tool_name=plan_vacation.
- Vacation plan items can only be inserted/updated while the parent vacation_plans.status is in (draft, planning); once ready/cancelled/failed, items are read-only.
- API usage must be enforced per api_keys: if daily_requests_used >= daily_request_limit for the current usage_window_start day window, new requests must be recorded with status=rate_limited and not executed against upstream.
- All foreign keys must be valid at write time; deleting a vacation_plans row must cascade delete vacation_plan_items.
- Coordinates must always validate within valid ranges; invalid coordinates must result in a failed request log row with error_code=invalid_coordinates.