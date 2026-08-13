# Flight & Stay Search Server (Duffel API) — local MCP environment

This backend stores end-user travel search sessions for flights and stays, including the normalized search criteria, returned offers/results, and downstream detail/review fetches. The main workflow is: create a search session, persist the request criteria, store the third-party (Duffel / hotel) response as offers and stay properties, then serve detail and review lookups from cached data while tracking lifecycle/status and request auditing.

Repository: https://github.com/clockworked247/flights-mcp-ts
Homepage: https://smithery.ai/server/@clockworked247/flights-mcp-ts

## Datastore

- `search_sessions.json` — Top-level search session representing a single user intent (flight search, multi-city, stay search). Used to group requests, results, and subsequent detail/review fetches and provide auditability and caching. (19 rows; fields: ['id', 'session_type', 'status', 'client_request_id', 'source', 'user_agent', 'ip_address', 'currency', 'locale', 'expires_at', 'provider', 'provider_request_payload', 'provider_response_payload', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['created', 'running', 'completed', 'failed', 'expired', 'cancelled']
  - constraint: unique(client_request_id, session_type) WHERE client_request_id IS NOT NULL
  - constraint: expires_at > created_at
  - constraint: provider IN ('duffel','hotel_provider','mixed')
  - constraint: session_type IN ('flight','multi_city','stay')
- `flight_search_requests.json` — Normalized criteria for flight searches (including multi-city). One row per search session of type flight or multi_city. (19 rows; fields: ['id', 'session_id', 'trip_type', 'cabin_class', 'adult_count', 'child_count', 'infant_count', 'max_connections', 'preferred_airlines', 'excluded_airlines', 'segment_criteria', 'flex_days', 'status', 'provider_search_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'submitted', 'succeeded', 'failed']
  - constraint: unique(session_id)
  - constraint: adult_count >= 1
  - constraint: child_count >= 0
  - constraint: infant_count >= 0
- `flight_offers.json` — Materialized flight offers returned from provider searches. Supports listing search results and retrieving offer details. (19 rows; fields: ['id', 'session_id', 'flight_search_request_id', 'provider', 'provider_offer_id', 'total_amount', 'total_currency', 'tax_amount', 'base_amount', 'slices', 'passenger_pricing', 'baggage_allowance', 'refundable', 'changeable', 'status', 'valid_until', 'raw_offer_payload', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'invalid']
  - constraint: unique(provider, provider_offer_id)
  - constraint: total_amount >= 0
  - constraint: total_currency ~ '^[A-Z]{3}$'
  - constraint: tax_amount IS NULL OR tax_amount >= 0
- `stay_search_requests.json` — Normalized criteria for stay searches (city/geo, check-in/out, occupancy, filters). One row per search session of type stay. (18 rows; fields: ['id', 'session_id', 'destination', 'check_in_date', 'check_out_date', 'room_count', 'adult_count', 'child_count', 'min_price_per_night', 'max_price_per_night', 'star_ratings', 'amenities', 'status', 'provider_search_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'submitted', 'succeeded', 'failed']
  - constraint: unique(session_id)
  - constraint: room_count >= 1 AND room_count <= 8
  - constraint: adult_count >= 1
  - constraint: child_count >= 0
- `stay_properties.json` — Materialized stay/hotel properties returned from stay searches, including cached review summaries and raw payloads. Supports search_stays and get_stay_reviews. (19 rows; fields: ['id', 'session_id', 'stay_search_request_id', 'provider', 'provider_property_id', 'name', 'address', 'geo', 'star_rating', 'nightly_price', 'price_currency', 'images', 'amenities', 'review_summary', 'reviews_cache', 'reviews_cached_at', 'status', 'raw_property_payload', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'unavailable']
  - constraint: unique(provider, provider_property_id, stay_search_request_id)
  - constraint: nightly_price IS NULL OR nightly_price >= 0
  - constraint: price_currency IS NULL OR price_currency ~ '^[A-Z]{3}$'
  - constraint: star_rating IS NULL OR (star_rating >= 0 AND star_rating <= 5)

## Business rules enforced by the tools

- search_flights creates a search_sessions row with session_type='flight' and provider='duffel', then creates exactly one flight_search_requests row for that session, moves session status created->running->completed|failed, and upserts flight_offers linked to that flight_search_requests row.
- search_multi_city creates a search_sessions row with session_type='multi_city' and a flight_search_requests row with trip_type='multi_city' and segment_criteria length between 2 and 6, then stores resulting flight_offers.
- get_offer_details must accept an upstream provider offer id (mapped to flight_offers.provider_offer_id) and return raw_offer_payload when present; if missing or stale/invalid, it must refresh from provider and update flight_offers.raw_offer_payload and updated_at, potentially changing status stale->active or active->invalid on provider errors.
- search_stays creates a search_sessions row with session_type='stay' and provider='hotel_provider', then creates exactly one stay_search_requests row, moves session status created->running->completed|failed, and upserts stay_properties linked to that stay_search_requests row.
- get_stay_reviews must locate a stay_properties row by provider_property_id, return reviews_cache when reviews_cached_at is within freshness window (e.g., 24h) and status != 'unavailable'; otherwise it must fetch from provider, update reviews_cache/reviews_cached_at/review_summary, and set status to active or unavailable based on provider response.
- A session is expired when now() >= expires_at; expired sessions must not be used to serve cached offers/properties unless explicitly allowed by configuration, and their status must transition completed|failed->expired via a background job.
- Idempotency: if client_request_id is provided and a matching non-expired session exists for the same session_type, the system must return the existing session and not create duplicate flight_search_requests/stay_search_requests rows.
- Data integrity: flight_offers must always reference an existing flight_search_requests row whose session_id matches flight_offers.session_id; similarly stay_properties must reference a stay_search_requests row whose session_id matches stay_properties.session_id.
- Quota/safety: each search session may store at most 500 flight_offers and at most 500 stay_properties; additional results must be truncated or stored in provider_response_payload only.
- PII/secrets: provider_request_payload and provider_response_payload must be redacted to remove API keys, payment instruments, and passenger PII before persistence.