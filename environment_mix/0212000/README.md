# Google Calendar Integration Server — local MCP environment

This backend stores Google OAuth connections and a local cache/log of calendar events accessed or created through the integration server. Main workflows: validate an access token against a stored OAuth connection, list events in a time range (optionally using cached data), fetch a specific event by its Google event id, and create new events while recording the request/response and normalizing attendees.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@MaheshtheDev/gcal-mcp

## Datastore

- `oauth_connections.json` — Represents a Google OAuth connection (identity + token metadata) used to call Google Calendar. Access tokens presented to tools are validated/associated to one of these connections (typically via token hash or introspection). (18 rows; fields: ['id', 'provider', 'google_user_id', 'primary_calendar_id', 'scopes', 'access_token_hash', 'refresh_token_ciphertext', 'token_expires_at', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'error']
  - constraint: unique(provider, google_user_id, primary_calendar_id)
  - constraint: provider = 'google'
  - constraint: token_expires_at is null OR token_expires_at > created_at
- `events.json` — Locally cached/recorded Google Calendar events for connections. Used to serve get-event and list-events quickly when available, and to track events created via the integration. (18 rows; fields: ['id', 'oauth_connection_id', 'google_event_id', 'calendar_id', 'summary', 'description', 'location', 'start_time', 'end_time', 'time_zone', 'etag', 'html_link', 'source', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['confirmed', 'cancelled', 'tentative', 'deleted_local']
  - constraint: foreign key(oauth_connection_id) references oauth_connections(id) on delete cascade
  - constraint: unique(oauth_connection_id, calendar_id, google_event_id)
  - constraint: end_time > start_time
  - constraint: char_length(summary) between 1 and 1024
- `event_attendees.json` — Normalized attendee emails for events created/fetched, corresponding to create-event.attendees and returned attendees on reads. (18 rows; fields: ['id', 'event_id', 'email', 'response_status', 'optional', 'created_at', 'updated_at'])
  - constraint: foreign key(event_id) references events(id) on delete cascade
  - constraint: unique(event_id, lower(email))
  - constraint: char_length(email) between 3 and 320
- `api_requests.json` — Audit log of tool invocations (list-events, get-event, create-event), mapping tool parameters to stored request fields, tracking execution status, and enabling debugging/rate limiting. (19 rows; fields: ['id', 'oauth_connection_id', 'tool_name', 'access_token_hash', 'time_min', 'time_max', 'max_results', 'google_event_id', 'create_summary', 'create_start_time', 'create_end_time', 'create_time_zone', 'create_attendees', 'http_status', 'error_code', 'error_message', 'status', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'validated', 'calling_google', 'succeeded', 'failed']
  - constraint: foreign key(oauth_connection_id) references oauth_connections(id) on delete set null
  - constraint: max_results is null OR (max_results >= 1 AND max_results <= 2500)
  - constraint: http_status is null OR (http_status >= 100 AND http_status <= 599)
  - constraint: tool_name = 'list-events' implies (time_min is not null AND time_max is not null)

## Business rules enforced by the tools

- For every tool call, accessToken must be hashed and stored in api_requests.access_token_hash; raw access tokens must never be persisted.
- list-events: timeMin and timeMax must parse as ISO datetimes and satisfy timeMax > timeMin; maxResults defaults to 250 when omitted and must be within [1, 2500].
- get-event: eventId must be non-empty; the server must attempt to resolve (oauth_connection_id, primary_calendar_id, eventId) and, when successful, upsert into events with google_event_id=eventId and set last_synced_at=now().
- create-event: startTime and endTime must parse as ISO datetimes and satisfy endTime > startTime; timeZone defaults to 'UTC' when omitted.
- create-event: attendees, if provided, must contain at most 2000 emails; each email is stored lowercased in event_attendees and deduplicated per event.
- When create-event succeeds against Google, the server must insert/update events with source='created_via_api', store the returned google_event_id, and set status to the Google event status when provided, else 'confirmed'.
- events uniqueness: within a given oauth_connection_id and calendar_id, google_event_id must be unique; conflicting inserts must be treated as an upsert (update summary/times/etag/last_synced_at).
- oauth_connections.status='revoked' must cause tool calls to fail validation before any Google API call (api_requests.status transitions to failed with error_code='oauth_revoked').
- Rate limiting/quota: per oauth_connection_id, no more than 60 api_requests with status in ('received','validated','calling_google') may exist within any rolling 60-second window; excess requests must be rejected and logged with status='failed' and error_code='rate_limited'.