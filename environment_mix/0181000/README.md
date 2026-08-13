# Date and Time Server — local MCP environment

This backend supports a date/time utility API that returns the current timestamp formatted for a requested timezone/locale and provides metadata about IANA timezones. It persists request logs for observability, caches timezone metadata for fast repeated lookups, and enforces per-client API key quotas and status/lifecycle rules.

Repository: https://github.com/chirag127/date-and-time-mcp-server
Homepage: https://smithery.ai/server/@chirag127/date-and-time-mcp-server

## Datastore

- `api_keys.json` — API credentials used to authenticate callers and enforce quotas/rate limits for date/time and timezone info requests. (18 rows; fields: ['id', 'key_hash', 'key_prefix', 'display_name', 'status', 'quota_requests_per_minute', 'quota_requests_per_day', 'allowed_timezones', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: quota_requests_per_minute >= 0
  - constraint: quota_requests_per_day >= 0
- `timezone_catalog.json` — Catalog/cache of IANA timezones and derived metadata used by getTimezoneInfo and for validating timezone inputs. (18 rows; fields: ['id', 'iana_name', 'status', 'country_code', 'utc_offset_seconds', 'dst_in_effect', 'abbreviation', 'last_refresh_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated']
  - constraint: unique(iana_name)
  - constraint: utc_offset_seconds between -64800 and 64800
- `datetime_requests.json` — Immutable request log for getCurrentDateTime calls, capturing requested formatting/timezone/locale and the resolved output metadata for debugging and analytics. (18 rows; fields: ['id', 'api_key_id', 'tool_name', 'status', 'format', 'timezone', 'timezone_id', 'locale', 'resolved_at_utc', 'resolved_at_local', 'response_value', 'response_unix_seconds', 'error_code', 'error_message', 'client_ip', 'user_agent', 'created_at', 'updated_at'])
  - lifecycle `status`: ['accepted', 'succeeded', 'failed', 'rejected']
  - constraint: tool_name = 'getCurrentDateTime'
  - constraint: response_unix_seconds is null or response_unix_seconds >= 0
  - constraint: timezone_id is null or timezone is not null
  - constraint: status in ('accepted','succeeded','failed','rejected')
- `timezone_info_requests.json` — Immutable request log for getTimezoneInfo calls, capturing the requested timezone and the resolved metadata snapshot returned. (19 rows; fields: ['id', 'api_key_id', 'tool_name', 'status', 'timezone', 'timezone_id', 'returned_country_code', 'returned_utc_offset_seconds', 'returned_dst_in_effect', 'returned_abbreviation', 'error_code', 'error_message', 'client_ip', 'user_agent', 'created_at', 'updated_at'])
  - lifecycle `status`: ['accepted', 'succeeded', 'failed', 'rejected']
  - constraint: tool_name = 'getTimezoneInfo'
  - constraint: timezone is not null
  - constraint: returned_utc_offset_seconds is null or returned_utc_offset_seconds between -64800 and 64800
  - constraint: timezone_id is null or timezone is not null
- `api_usage_rollups.json` — Materialized usage counters used to enforce per-key quotas (per-minute and per-day) without scanning request logs. (16 rows; fields: ['id', 'api_key_id', 'window_type', 'window_start', 'requests_total', 'requests_rejected', 'created_at', 'updated_at'])
  - constraint: unique(api_key_id, window_type, window_start)
  - constraint: requests_total >= 0
  - constraint: requests_rejected >= 0
  - constraint: requests_rejected <= requests_total

## Business rules enforced by the tools

- getCurrentDateTime(format, timezone, locale) must record a datetime_requests row with tool_name='getCurrentDateTime' for every invocation that passes authentication; rows start in status='accepted' and must transition exactly once to succeeded|failed|rejected.
- getTimezoneInfo(timezone) must record a timezone_info_requests row with tool_name='getTimezoneInfo' for every invocation that passes authentication; rows start in status='accepted' and must transition exactly once to succeeded|failed|rejected.
- If an API key status is not 'active' then both tools must be rejected and a corresponding request log row must be written with status='rejected' and error_code='KEY_INACTIVE'.
- Timezone inputs must be validated as IANA identifiers; if invalid or unknown, the request must be marked failed or rejected with error_code='INVALID_TIMEZONE' and timezone_id must remain null.
- If api_keys.allowed_timezones is non-empty, then timezone (when provided) must be a member of that list or the request must be rejected with error_code='TIMEZONE_NOT_ALLOWED'.
- format for getCurrentDateTime may be null (server default) or one of: 'ISO','UNIX','RFC2822','HTTP','SQL', or a custom format string; invalid formats must yield status='failed' with error_code='INVALID_FORMAT'.
- Quota enforcement: before accepting a request, the service must ensure that api_usage_rollups for (api_key_id, minute window) will not exceed api_keys.quota_requests_per_minute and (api_key_id, day window) will not exceed api_keys.quota_requests_per_day; otherwise the request must be rejected with error_code='QUOTA_EXCEEDED' and increment requests_rejected.
- On accepting a request (status='accepted'), increment api_usage_rollups.requests_total for the current minute and day windows; on rejection increment both requests_total and requests_rejected (so rejected traffic is measurable).
- timezone_catalog.iana_name must be unique; getTimezoneInfo should prefer returning metadata from timezone_catalog if present, otherwise compute metadata, optionally insert it, and set last_refresh_at.
- utc_offset_seconds and returned_utc_offset_seconds must remain within [-64800, 64800] to prevent invalid timezone offset data.