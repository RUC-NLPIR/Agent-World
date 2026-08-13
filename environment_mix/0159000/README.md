# Call For Papers MCP — local MCP environment

This backend stores conference/event listings (call-for-papers style) and supports keyword search over them. The primary workflow is ingesting/updating event records from external CFP sources, then serving read-only keyword queries with result limiting while tracking query usage for operational visibility.

Repository: https://github.com/alperenkocyigit/call-for-papers-mcp
Homepage: https://smithery.ai/server/@alperenkocyigit/call-for-papers-mcp

## Datastore

- `events.json` — Canonical conference/event records returned by the API. One row per distinct event edition, with searchable title/description and key dates. (36 rows; fields: ['id', 'source_id', 'source_url', 'title', 'description', 'location', 'start_date', 'end_date', 'cfp_deadline', 'topics', 'organizer', 'status', 'search_document', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'cancelled', 'deleted']
  - constraint: required(title, status, search_document, created_at, updated_at)
  - constraint: unique(source_url) WHERE source_url IS NOT NULL
  - constraint: unique(source_id) WHERE source_id IS NOT NULL
  - constraint: start_date <= end_date WHERE start_date IS NOT NULL AND end_date IS NOT NULL
- `search_queries.json` — Audit log of keyword searches issued to get_events, used for debugging, rate limiting, and analytics. (30 rows; fields: ['id', 'api_key_id', 'keywords', 'normalized_keywords', 'limit', 'status', 'error_message', 'results_count', 'execution_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'completed', 'failed']
  - constraint: required(keywords, normalized_keywords, limit, status, created_at, updated_at)
  - constraint: char_length(keywords) BETWEEN 1 AND 500
  - constraint: limit BETWEEN 1 AND 100
  - constraint: results_count >= 0 WHERE results_count IS NOT NULL
- `search_query_results.json` — Materialized per-query result rows mapping a search query to the events returned (top-N). Enables debugging, replay, and evaluation. (30 rows; fields: ['id', 'search_query_id', 'event_id', 'rank', 'score', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active']
  - constraint: required(search_query_id, event_id, rank, created_at, updated_at)
  - constraint: foreign_key(search_query_id) references search_queries(id) ON DELETE CASCADE
  - constraint: foreign_key(event_id) references events(id) ON DELETE RESTRICT
  - constraint: unique(search_query_id, rank)
- `api_keys.json` — API keys for authenticating clients and enforcing quotas. Optional for this MCP, but typical in production search APIs and supports operational controls. (31 rows; fields: ['id', 'key_hash', 'name', 'status', 'daily_limit', 'created_at', 'updated_at', 'revoked_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: required(key_hash, name, status, daily_limit, created_at, updated_at)
  - constraint: unique(key_hash)
  - constraint: daily_limit BETWEEN 0 AND 1000000
  - constraint: revoked_at IS NOT NULL WHEN status='revoked'
- `ingestion_jobs.json` — Background ingestion/sync jobs that pull CFP events from external sources, parse them, and upsert into events. (30 rows; fields: ['id', 'source_name', 'source_url', 'status', 'started_at', 'finished_at', 'events_upserted', 'events_skipped', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: required(source_name, status, events_upserted, events_skipped, created_at, updated_at)
  - constraint: events_upserted >= 0
  - constraint: events_skipped >= 0
  - constraint: started_at <= finished_at WHERE started_at IS NOT NULL AND finished_at IS NOT NULL

## Business rules enforced by the tools

- get_events must require keywords; the request is rejected if keywords is empty/blank after trimming.
- get_events.limit defaults to 10 when not provided and must be clamped/rejected to the inclusive range [1, 100].
- Each get_events call creates a search_queries row with status='received', then transitions to 'completed' or 'failed' exactly once.
- A completed get_events call may only return events where events.status='active'.
- For each completed query, at most limit rows are inserted into search_query_results with ranks 1..N, and (search_query_id, rank) must be unique.
- If an api_key is provided, it must exist and have status='active'; revoked keys cannot create search_queries rows.
- If an api_key has daily_limit > 0, the system must enforce that the number of search_queries created for that key per UTC day does not exceed daily_limit.
- Ingestion jobs are the only writer for events in production; they upsert by source_url when present, otherwise by source_id when present, otherwise insert a new event.