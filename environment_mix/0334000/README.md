# Airbnb Search and Listing Server — local MCP environment

This backend stores cached Airbnb search queries and resulting listing snapshots, plus detailed listing snapshots fetched on demand. The main workflows are: (1) execute a location-based search with optional filters/pagination and persist the query + page cursor and listing result set, and (2) fetch listing details for a given Airbnb listing id for a given stay/guest context, storing a versioned detail snapshot for later reads and debugging.

Repository: https://github.com/openbnb-org/mcp-server-airbnb
Homepage: https://smithery.ai/server/@openbnb-org/mcp-server-airbnb

## Datastore

- `airbnb_search_queries.json` — A normalized record of each Airbnb search request (filters, stay context, pagination cursor) and its execution status. (19 rows; fields: ['id', 'location', 'place_id', 'checkin', 'checkout', 'adults', 'children', 'infants', 'pets', 'min_price', 'max_price', 'cursor', 'ignore_robots_text', 'request_fingerprint', 'executed_at', 'completed_at', 'error_code', 'error_message', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: ignore_robots_text IN (true,false)
  - constraint: adults IS NULL OR adults >= 0
  - constraint: children IS NULL OR children >= 0
  - constraint: infants IS NULL OR infants >= 0
- `airbnb_listings.json` — Canonical listing identity table keyed by Airbnb listing ID; stores stable attributes and the current best-known URL. (18 rows; fields: ['id', 'airbnb_listing_id', 'canonical_url', 'title', 'status', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'deleted', 'unknown']
  - constraint: airbnb_listing_id UNIQUE
  - constraint: canonical_url NOT NULL
- `airbnb_search_results.json` — Join table between a search query and the listings returned for that query, including rank/order and lightweight card snapshot fields. (18 rows; fields: ['id', 'search_query_id', 'listing_id', 'rank', 'cursor_used', 'price_total', 'price_currency', 'rating', 'review_count', 'raw_card', 'created_at', 'updated_at'])
  - lifecycle `status`: ['present', 'filtered_out', 'removed']
  - constraint: FOREIGN KEY(search_query_id) REFERENCES airbnb_search_queries(id) ON DELETE CASCADE
  - constraint: FOREIGN KEY(listing_id) REFERENCES airbnb_listings(id) ON DELETE RESTRICT
  - constraint: unique(search_query_id, listing_id)
  - constraint: rank >= 0
- `airbnb_listing_detail_snapshots.json` — Versioned detailed listing payloads fetched via the listing details tool, parameterized by stay dates and guest counts. (19 rows; fields: ['id', 'listing_id', 'checkin', 'checkout', 'adults', 'children', 'infants', 'pets', 'ignore_robots_text', 'source_url', 'raw_details', 'fetched_at', 'status', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'failed']
  - constraint: FOREIGN KEY(listing_id) REFERENCES airbnb_listings(id) ON DELETE CASCADE
  - constraint: ignore_robots_text IN (true,false)
  - constraint: adults IS NULL OR adults >= 0
  - constraint: children IS NULL OR children >= 0

## Business rules enforced by the tools

- airbnb_search must create (or reuse) an airbnb_search_queries row keyed by request_fingerprint; if an existing row is in status=succeeded and is fresh per TTL, the implementation may return cached results without re-fetching upstream.
- For airbnb_search execution, if placeId is provided it must be stored in place_id and treated as the effective location spec; location is still stored as provided to satisfy the tool requirement, but request_fingerprint must be computed using place_id when present (otherwise location).
- airbnb_search must validate cursor as a base64 string when present; invalid cursor causes status=failed with error_code=INVALID_INPUT.
- airbnb_search must enforce that when both checkin and checkout are provided, checkin < checkout; otherwise the query is rejected (failed) with error_code=INVALID_INPUT.
- airbnb_search must persist one airbnb_search_results row per unique (search_query_id, listing_id) with a non-negative rank; the returned tool response should be ordered by rank.
- airbnb_search must upsert airbnb_listings by airbnb_listing_id; canonical_url must be populated to provide direct links in responses.
- airbnb_listing_details must upsert airbnb_listings by airbnb_listing_id derived from the tool parameter id, then create a new airbnb_listing_detail_snapshots row for each fetch attempt (no in-place overwrite) to preserve history.
- airbnb_listing_details must validate that when both checkin and checkout are provided, checkin < checkout; otherwise reject with error_code=INVALID_INPUT.
- If ignoreRobotsText=true for either tool, the request must only proceed when an internal policy flag (not exposed in tool parameters) allows it; otherwise the request is failed with error_code=POLICY_DENIED while still recording the attempted query/snapshot.
- On successful search or details fetch, airbnb_listings.last_seen_at must be set to the fetch time and status should transition to active unless upstream indicates removal/unavailability, in which case status may become inactive or deleted.
- FK integrity must hold: deleting a search query deletes its search results; deleting a listing deletes its detail snapshots; listings referenced by search results cannot be deleted unless those results are removed first.