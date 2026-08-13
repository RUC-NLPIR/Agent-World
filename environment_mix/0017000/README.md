# Hotel Booking Server — local MCP environment

This backend supports place lookup, hotel availability search with pagination sessions, detailed hotel/rate retrieval, and initiating bookings that generate secure payment links. It stores normalized hotel catalog data (hotels, facilities, rates) plus per-user search sessions/results and booking attempts tied to a selected rate option.

Repository: https://github.com/jinkoso/jinko-mcp
Homepage: https://smithery.ai/server/@jinkoso/jinko-mcp

## Datastore

- `places.json` — Standardized place records returned from text queries (cities, landmarks, hotels) with coordinates and display metadata. Used by find-place and as optional context for hotel searches. (18 rows; fields: ['id', 'source', 'source_place_id', 'display_name', 'normalized_name', 'place_type', 'latitude', 'longitude', 'country_code', 'admin1', 'locality', 'language', 'raw_payload', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded', 'deleted']
  - constraint: unique(source, source_place_id)
  - constraint: latitude between -90 and 90
  - constraint: longitude between -180 and 180
  - constraint: language ~ '^[a-z]{2}(-[A-Z]{2})?$'
- `facilities.json` — Canonical facility/amenity definitions and their localized names. Returned by get-facilities and used to filter hotel searches. (18 rows; fields: ['id', 'external_facility_id', 'category', 'default_name', 'localized_names', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated']
  - constraint: unique(external_facility_id)
  - constraint: external_facility_id > 0
- `hotels.json` — Hotel catalog and base attributes used in search results and hotel detail views. Includes facility membership for filtering and display. (18 rows; fields: ['id', 'source', 'source_hotel_id', 'name', 'address_line1', 'address_line2', 'city', 'region', 'postal_code', 'country_code', 'latitude', 'longitude', 'star_rating', 'description', 'check_in_time', 'check_out_time', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'deleted']
  - constraint: unique(source, source_hotel_id)
  - constraint: latitude between -90 and 90
  - constraint: longitude between -180 and 180
  - constraint: star_rating is null or (star_rating >= 0 and star_rating <= 5)
- `hotel_facilities.json` — Join table mapping hotels to the facilities they offer. Used to filter search-hotels by facility IDs and to render amenity lists. (18 rows; fields: ['id', 'hotel_id', 'facility_id', 'is_available', 'notes', 'created_at', 'updated_at'])
  - constraint: unique(hotel_id, facility_id)
  - constraint: fk hotel_id references hotels.id on delete cascade
  - constraint: fk facility_id references facilities.id on delete restrict
- `search_sessions.json` — Stateful hotel search sessions used for pagination (session_id) and to scope subsequent operations like get-hotel-details and book-hotel to a consistent search context. (19 rows; fields: ['id', 'query_place_id', 'latitude', 'longitude', 'name', 'check_in_date', 'check_out_date', 'adults', 'children', 'search_context', 'facility_external_ids', 'language', 'page_size', 'next_offset', 'has_more', 'status', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'exhausted', 'expired', 'cancelled']
  - constraint: latitude between -90 and 90
  - constraint: longitude between -180 and 180
  - constraint: adults >= 1
  - constraint: children >= 0
- `bookings.json` — Booking attempts/transactions initiated from a search session for a specific hotel and rate option, including generated payment link and status transitions. (20 rows; fields: ['id', 'session_id', 'hotel_id', 'rate_id', 'check_in_date', 'check_out_date', 'adults', 'children', 'payment_link_url', 'payment_link_expires_at', 'currency', 'total_price', 'status', 'failure_reason', 'provider_booking_id', 'provider_payload', 'created_at', 'updated_at'])
  - lifecycle `status`: ['initiated', 'payment_pending', 'paid', 'confirmed', 'cancelled', 'expired', 'failed']
  - constraint: fk session_id references search_sessions.id on delete restrict
  - constraint: fk hotel_id references hotels.id on delete restrict
  - constraint: adults >= 1
  - constraint: children >= 0

## Business rules enforced by the tools

- find-place(query, language) performs a normalized lookup against places.normalized_name plus provider fetch; any newly fetched place must be upserted by unique(source, source_place_id) with language set to the request language.
- get-facilities(language) returns facilities where status='active', using facilities.localized_names[language] when present, otherwise facilities.default_name; language must be one of: en, es, it, he, ar, de.
- search-hotels must create a search_sessions row with status='active', page_size<=50, next_offset=0, has_more computed from total matches, and expires_at set (e.g., created_at + 30 minutes).
- search-hotels must enforce adults>=1 and children>=0; check_out_date must be strictly after check_in_date; latitude/longitude must be within valid ranges.
- When search-hotels receives facilities (array of numbers), each value must match an existing facilities.external_facility_id with facilities.status='active'; otherwise the request must fail validation.
- search-hotels filtering by facilities means a hotel must have matching hotel_facilities rows (is_available=true) for all requested external facility IDs.
- load-more-hotels(session_id) must only operate on search_sessions where status='active' and expires_at > now(); it returns the next page and increments search_sessions.next_offset by page_size; when no more results remain, it sets has_more=false and transitions status to 'exhausted'.
- get-hotel-details(session_id, hotel_id) must only allow session_id that exists and is not expired/cancelled; hotel_id must exist and be status='active'.
- get-hotel-details must return rate options for the given hotel scoped to the session parameters; the returned rate_id values must be the same identifiers accepted by book-hotel.rate_id.
- book-hotel(session_id, hotel_id, rate_id) must reject if the session is expired/cancelled or if hotel_id is not part of the session's current result set (as of the session filters).
- book-hotel must create a bookings row with status transitioning from 'initiated' to 'payment_pending' only after a payment_link_url and payment_link_expires_at are successfully generated.
- A booking's payment_link_expires_at must be <= search_sessions.expires_at for the associated session (payment link cannot outlive the search session context).
- Only one active booking attempt per (session_id, hotel_id, rate_id) may exist at a time for statuses in ('initiated','payment_pending','paid'); duplicates must be prevented by constraint or transactional check.