# iFood Remote Server — local MCP environment

This backend stores restaurant discovery data and the operational metadata needed to serve a minimal search API. The main workflow is: a client submits a search term, the service logs the search query, matches restaurants by name/cuisine/tags, and returns active restaurants while tracking request usage.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@pccassin/food-remote-mcp

## Datastore

- `api_keys.json` — API credentials allowed to call the service, including status and basic quota/rate settings used to authorize and throttle requests. (26 rows; fields: ['id', 'key_hash', 'key_prefix', 'owner_name', 'status', 'requests_per_minute_limit', 'requests_per_day_limit', 'requests_today', 'requests_today_reset_at', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: requests_per_minute_limit >= 1
  - constraint: requests_per_day_limit >= 1
- `restaurants.json` — Restaurant catalog used for search results, including name, location metadata, cuisine classification, and availability status. (32 rows; fields: ['id', 'external_provider', 'external_id', 'name', 'normalized_name', 'cuisine', 'tags', 'city', 'state', 'country', 'latitude', 'longitude', 'price_level', 'rating_avg', 'rating_count', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'temporarily_unavailable', 'closed']
  - constraint: unique(external_provider, external_id) WHERE external_id IS NOT NULL
  - constraint: name <> ''
  - constraint: normalized_name <> ''
  - constraint: country IN ('BR')
- `search_queries.json` — Log of restaurant search requests. Each get_restaurants call creates a record capturing the input term, derived normalization, and request outcome metadata. (32 rows; fields: ['id', 'api_key_id', 'term', 'normalized_term', 'status', 'result_count', 'error_code', 'error_message', 'client_ip', 'user_agent', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'completed', 'failed']
  - constraint: term <> ''
  - constraint: normalized_term <> ''
  - constraint: result_count >= 0 OR result_count IS NULL
  - constraint: error_code IS NULL OR status = 'failed'
- `search_results.json` — Join table capturing which restaurants were returned for a given search query and their ranking score/order at the time of response. (31 rows; fields: ['id', 'search_query_id', 'restaurant_id', 'rank', 'match_score', 'created_at', 'updated_at'])
  - constraint: unique(search_query_id, restaurant_id)
  - constraint: unique(search_query_id, rank)
  - constraint: rank >= 1
  - constraint: match_score >= 0

## Business rules enforced by the tools

- list_tools returns a static/tooling-defined list and does not mutate storage; it may still be subject to API key auth and request counting via api_keys.
- get_restaurants(term) MUST create a search_queries row with term and normalized_term; status starts as 'received' and transitions to 'completed' or 'failed' only.
- get_restaurants(term) MUST only return restaurants where restaurants.status = 'active'.
- get_restaurants(term) MUST persist the returned set into search_results with contiguous 1-based ranks and unique (search_query_id, restaurant_id).
- If get_restaurants fails before producing results, search_queries.status MUST be set to 'failed' and error_code/error_message populated; no search_results rows should be created for that query.
- API requests MUST be rejected when api_keys.status != 'active'.
- API requests MUST enforce requests_per_minute_limit and requests_per_day_limit; exceeding limits MUST not create search_results and SHOULD still create a search_queries row marked failed with an appropriate error_code (e.g., 'rate_limited' or 'quota_exceeded').
- api_keys.requests_today MUST reset at requests_today_reset_at when the UTC day changes; requests_today MUST never decrease except during a reset.
- Restaurant ingestion/updates MUST maintain normalized_name consistent with name and ensure rating_avg/rating_count/price_level remain within declared ranges.