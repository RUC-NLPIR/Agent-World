# Oura API Integration Server — local MCP environment

This backend stores Oura user connections (OAuth tokens), normalized daily wellness metrics (sleep, readiness, resilience), and a small sync/ingestion log so the server can fetch from Oura and cache results for fast reads. Main workflows are: (1) link an Oura account to a local user, (2) periodically or on-demand sync Oura data into daily tables, and (3) serve tool reads for today or recent history from the cached tables with fallback to refresh if stale.

Repository: https://github.com/tomekkorbak/oura-mcp-server
Homepage: https://smithery.ai/server/@tomekkorbak/oura-mcp-server

## Datastore

- `users.json` — Local identities that use the integration server. Used as the owner for Oura connections and all stored metrics. (18 rows; fields: ['id', 'external_subject', 'email', 'timezone', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(external_subject) where external_subject is not null
  - constraint: unique(email) where email is not null
- `oura_connections.json` — OAuth connection and token storage for accessing the Oura API on behalf of a user (refresh/access tokens, scopes, expiry). (18 rows; fields: ['id', 'user_id', 'provider', 'oura_user_id', 'scope', 'access_token', 'refresh_token', 'token_type', 'access_token_expires_at', 'last_token_refresh_at', 'status', 'last_error_code', 'last_error_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'error']
  - constraint: unique(user_id, provider)
  - constraint: access_token_expires_at is null or access_token_expires_at >= created_at
- `sleep_daily.json` — Daily sleep summaries cached from Oura. Supports 'get_sleep_data' (recent/history) and 'get_today_sleep_data'. (19 rows; fields: ['id', 'user_id', 'source_connection_id', 'day', 'score', 'total_sleep_duration_s', 'time_in_bed_s', 'deep_sleep_duration_s', 'rem_sleep_duration_s', 'light_sleep_duration_s', 'awake_time_s', 'average_heart_rate_bpm', 'lowest_heart_rate_bpm', 'average_hrv_ms', 'bedtime_start_at', 'bedtime_end_at', 'raw_payload', 'status', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['complete', 'partial', 'error']
  - constraint: unique(user_id, day)
  - constraint: score is null or (score >= 0 and score <= 100)
  - constraint: total_sleep_duration_s is null or total_sleep_duration_s >= 0
  - constraint: time_in_bed_s is null or time_in_bed_s >= 0
- `readiness_daily.json` — Daily readiness summaries cached from Oura. Supports 'get_readiness_data' and 'get_today_readiness_data'. (18 rows; fields: ['id', 'user_id', 'source_connection_id', 'day', 'score', 'temperature_deviation_c', 'resting_heart_rate_bpm', 'hrv_balance', 'sleep_balance', 'recovery_index', 'raw_payload', 'status', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['complete', 'partial', 'error']
  - constraint: unique(user_id, day)
  - constraint: score is null or (score >= 0 and score <= 100)
- `resilience_daily.json` — Daily resilience summaries cached from Oura. Supports 'get_resilience_data' and 'get_today_resilience_data'. (18 rows; fields: ['id', 'user_id', 'source_connection_id', 'day', 'level', 'score', 'raw_payload', 'status', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['complete', 'partial', 'error']
  - constraint: unique(user_id, day)
  - constraint: score is null or (score >= 0 and score <= 100)
- `sync_runs.json` — Log of on-demand/background pulls from Oura used to populate daily tables. Helps enforce rate limiting, staleness refresh, and debug failures. (18 rows; fields: ['id', 'user_id', 'connection_id', 'data_type', 'start_day', 'end_day', 'trigger', 'status', 'http_status', 'error_code', 'error_message', 'records_upserted', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: records_upserted >= 0
  - constraint: http_status is null or (http_status >= 100 and http_status <= 599)
  - constraint: start_day is null or end_day is null or start_day <= end_day

## Business rules enforced by the tools

- All tool calls resolve to exactly one active user; if the resolved user.status != 'active', tools must return an authorization/disabled error and not call upstream.
- Each user may have at most one active Oura connection (enforced by unique(user_id, provider) and connection.status). If the connection is revoked, tools must fail with a re-auth required error.
- For get_today_* tools, the server must compute 'today' using users.timezone and query the corresponding *_daily table by (user_id, day).
- For get_*_data tools (range/history), because the tool surface exposes no parameters, the server must use a fixed default range (e.g., last 30 days) and read rows where day between (today - default_days + 1) and today inclusive, ordered by day asc.
- Before serving results, if the newest cached row for the requested data_type has fetched_at older than a staleness threshold (e.g., 15 minutes for today, 6 hours for history) the server should enqueue a sync_runs row with trigger='tool_call' and attempt a refresh; on refresh failure it may fall back to cached data if present.
- Sync runs must only transition status according to sync_runs.lifecycle.transitions; a run cannot move from succeeded/failed/cancelled back to running.
- Ingestion upserts daily data by (user_id, day); duplicate rows for the same day are not allowed in sleep_daily/readiness_daily/resilience_daily.
- Metric constraints are enforced on write: score values must be within 0..100 when present; duration fields must be non-negative.
- Foreign key integrity: daily rows and sync_runs must reference an existing users row and an existing oura_connections row belonging to that same user_id; mismatched ownership is rejected.
- If upstream returns 401/invalid token during sync, the system must set oura_connections.status='error', populate last_error_code, and the corresponding sync_runs.status must be 'failed'.