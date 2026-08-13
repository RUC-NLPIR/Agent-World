# 12306 MCP Server — local MCP environment

This backend powers a minimal 12306 train-ticket search API. It stores normalized station/city reference data, a station-to-station query log (date/from/to), and cached search results (trains and seat availability) so repeated searches can be served quickly while respecting data freshness.

Repository: https://github.com/shenpeiheng/mcp-server-chinarailway
Homepage: https://smithery.ai/server/@shenpeiheng/mcp-server-chinarailway

## Datastore

- `cities.json` — Canonical list of Chinese cities used for mapping user-provided fromCity/toCity to known railway stations and for UI/display. (18 rows; fields: ['id', 'name_zh', 'name_en', 'province_zh', 'country_code', 'normalized_key', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(country_code, normalized_key)
  - constraint: name_zh <> ''
  - constraint: normalized_key <> ''
- `stations.json` — Railway stations (12306 '站点') used to resolve cities to station codes and to represent from/to endpoints for searches. (18 rows; fields: ['id', 'city_id', 'name_zh', 'station_code', 'telecode', 'is_primary_for_city', 'latitude', 'longitude', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(station_code)
  - constraint: unique(city_id, name_zh)
  - constraint: name_zh <> ''
  - constraint: station_code <> ''
- `search_queries.json` — User searches executed via the MCP tool `search(date, fromCity, toCity)`. Stores normalized resolution to stations/cities and execution metadata for debugging, rate limiting, and caching decisions. (18 rows; fields: ['id', 'travel_date', 'from_city_raw', 'to_city_raw', 'from_city_id', 'to_city_id', 'from_station_id', 'to_station_id', 'status', 'resolution_status', 'error_code', 'error_message', 'upstream_source', 'cache_key', 'request_fingerprint', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: travel_date matches regex ^\d{4}-\d{2}-\d{2}$
  - constraint: from_city_raw <> ''
  - constraint: to_city_raw <> ''
  - constraint: cache_key <> ''
- `search_result_sets.json` — Cached result set for a specific query signature (date + from/to station). One query can produce at most one result set row per cache_key version, and each result set expands into many train rows. (18 rows; fields: ['id', 'cache_key', 'travel_date', 'from_station_id', 'to_station_id', 'status', 'fetched_at', 'expires_at', 'upstream_etag', 'raw_payload', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'invalid']
  - constraint: unique(cache_key)
  - constraint: travel_date matches regex ^\d{4}-\d{2}-\d{2}$
  - constraint: expires_at >= fetched_at
- `train_services.json` — Individual trains returned within a cached result set, including schedule and seat/price availability by seat type as structured JSON. (18 rows; fields: ['id', 'result_set_id', 'train_no', 'from_station_name_zh', 'to_station_name_zh', 'depart_time', 'arrive_time', 'duration_minutes', 'day_offset', 'seat_availability', 'prices', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: unique(result_set_id, train_no, depart_time, arrive_time)
  - constraint: day_offset >= 0 AND day_offset <= 7
  - constraint: duration_minutes is null OR duration_minutes >= 0
  - constraint: depart_time matches regex ^\d{2}:\d{2}$

## Business rules enforced by the tools

- The `search` tool must require and validate all three parameters: date, fromCity, toCity; date must be a valid calendar date string in YYYY-MM-DD format.
- When handling `search`, the service must attempt to resolve fromCity/toCity to cities via cities.normalized_key and then select stations: if multiple stations exist, prefer stations.is_primary_for_city=true; if none, the query is recorded with resolution_status indicating which side failed and status=failed.
- A cache_key must be computed deterministically from (travel_date, from_station.station_code, to_station.station_code). For the same cache_key, at most one row may exist in search_result_sets (unique(cache_key)).
- If a non-invalid cached result set exists and expires_at > now(), `search` should serve data from cache and record search_queries.upstream_source='cache'; otherwise it must fetch upstream and upsert the search_result_sets row with status='fresh', fetched_at=now(), expires_at=now()+TTL.
- On upstream fetch success, train_services rows for the result_set_id must be replaced atomically (delete/mark removed then insert active) so the cached set is internally consistent.
- search_queries.status transitions must follow: queued -> running -> (succeeded|failed); succeeded/failed are terminal.
- Station and city reference data cannot be deleted while referenced by search_queries/search_result_sets/stations; they may only be disabled (status='disabled').
- Seat availability and price fields are stored as structured objects; the API layer must ensure they are JSON-serializable objects and must not exceed a configured maximum payload size per train and per result set.