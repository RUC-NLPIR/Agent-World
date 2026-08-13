# FlightRadar — local MCP environment

This backend stores periodically ingested flight-tracking snapshots, a normalized current-flight view, and lightweight API request logs to support listing/searching flights and retrieving status by flight number. The main workflow is: ingest raw provider data into snapshots, upsert/derive current flight state, and serve search/status queries while tracking usage and enforcing basic limits.

Repository: https://github.com/Cyreslab-AI/flightradar-mcp-server
Homepage: https://smithery.ai/server/@Cyreslab-AI/flightradar-mcp-server

## Datastore

- `api_keys.json` — API credentials for clients accessing the FlightRadar service, including quotas and lifecycle state. (18 rows; fields: ['id', 'key_hash', 'label', 'status', 'rate_limit_per_minute', 'daily_quota_requests', 'allowed_tools', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(key_hash)
  - constraint: rate_limit_per_minute between 1 and 6000
  - constraint: daily_quota_requests between 1 and 10000000
  - constraint: allowed_tools subset_of(['get_flight_data','search_flights','get_flight_status'])
- `ingestion_runs.json` — Tracks periodic imports from the upstream flight data source; used to explain freshness and support get_flight_data. (18 rows; fields: ['id', 'source', 'status', 'started_at', 'finished_at', 'records_ingested', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: records_ingested >= 0
  - constraint: finished_at is null when status in ('queued','running')
  - constraint: finished_at is not null when status in ('succeeded','failed')
- `flight_snapshots.json` — Append-only raw flight tracking points/snapshots as received from the upstream source; supports historical inspection and building the current flight state. (17 rows; fields: ['id', 'ingestion_run_id', 'source_flight_id', 'flight_number', 'callsign', 'airline_iata', 'airline_icao', 'aircraft_icao_type', 'registration', 'origin_iata', 'destination_iata', 'latitude', 'longitude', 'altitude_ft', 'ground_speed_kt', 'heading_deg', 'on_ground', 'event_time', 'raw_payload', 'created_at', 'updated_at'])
  - lifecycle `status`: ['valid', 'superseded', 'rejected']
  - constraint: foreign key(ingestion_run_id) references ingestion_runs(id) on delete restrict
  - constraint: unique(source_flight_id, event_time)
  - constraint: latitude between -90 and 90 when latitude is not null
  - constraint: longitude between -180 and 180 when longitude is not null
- `flights_current.json` — Materialized current/most-recent state per upstream flight id, optimized for search_flights and get_flight_status. (18 rows; fields: ['id', 'source_flight_id', 'latest_snapshot_id', 'flight_number', 'callsign', 'origin_iata', 'destination_iata', 'latitude', 'longitude', 'altitude_ft', 'ground_speed_kt', 'heading_deg', 'on_ground', 'status', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['scheduled', 'en_route', 'landed', 'cancelled', 'unknown']
  - constraint: unique(source_flight_id)
  - constraint: index(flight_number)
  - constraint: foreign key(latest_snapshot_id) references flight_snapshots(id) on delete restrict
  - constraint: last_seen_at <= now() + interval '5 minutes'
- `api_requests.json` — Audit/usage log of tool calls for rate limiting, quota enforcement, debugging and analytics. (18 rows; fields: ['id', 'api_key_id', 'tool_name', 'request_params', 'response_status', 'response_bytes', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'served', 'rejected']
  - constraint: foreign key(api_key_id) references api_keys(id) on delete restrict
  - constraint: response_status between 100 and 599
  - constraint: response_bytes >= 0
  - constraint: duration_ms >= 0

## Business rules enforced by the tools

- All tool calls MUST create an api_requests row with tool_name and request_params (empty object if none) and finalize it to status=served or status=rejected.
- Requests MUST be rejected when api_keys.status != 'active' or when tool_name is not contained in api_keys.allowed_tools.
- Rate limiting MUST enforce api_keys.rate_limit_per_minute by counting api_requests for the api_key_id within the last rolling 60 seconds (statuses received/served/rejected all count).
- Daily quota MUST enforce api_keys.daily_quota_requests by counting api_requests for the api_key_id within the current UTC day.
- get_flight_data MUST return data derived from flights_current joined to its latest flight_snapshots (and optionally freshness metadata from the latest succeeded ingestion_runs).
- search_flights MUST query flights_current as the primary index and may optionally enrich with latest snapshot fields; because the current tool surface has no parameters, the default behavior MUST be a bounded listing (e.g., most recently seen flights ordered by last_seen_at desc) with a hard maximum page size enforced server-side.
- get_flight_status MUST look up flights_current by normalized flight_number (trim spaces, uppercase) and return the matching record; if multiple current flights share a flight_number, the service MUST return the most recent by last_seen_at.
- Ingestion MUST insert append-only flight_snapshots and then upsert flights_current for each source_flight_id, setting latest_snapshot_id and last_seen_at to the newest event_time seen.
- A flight_snapshots row with duplicate (source_flight_id, event_time) MUST be rejected or deduplicated to preserve uniqueness.
- flights_current.status MUST be derived consistently from telemetry: if on_ground=true and ground_speed_kt is near 0 and altitude_ft is low -> landed/scheduled (depending on recency); if on_ground=false or altitude_ft above a minimum -> en_route; otherwise unknown; cancelled is only set by explicit provider signal in raw_payload.