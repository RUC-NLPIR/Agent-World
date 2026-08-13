# Bazi Calculator — local MCP environment

This backend stores BaZi (Eight Characters) calculation requests and their computed results, along with derived calendar (Huangli) outputs and reverse-lookup indexes from BaZi pillars to candidate solar datetimes. Main workflows are: accept a solar/lunar datetime + gender + sect, compute/return BaZi details, compute/return Chinese calendar info for a solar datetime, and reverse-resolve a BaZi string to one or more possible solar datetimes.

Repository: https://github.com/cantian-ai/bazi-mcp
Homepage: https://smithery.ai/server/@cantian-ai/bazi-mcp

## Datastore

- `bazi_requests.json` — Normalized record of an API request that asks to compute BaZi from either a solar datetime (ISO with timezone) or a lunar datetime (string form), including gender and the early/late Zi-hour sect option. Used by getBaziDetail/buildBaziFromSolarDatetime/buildBaziFromLunarDatetime. (20 rows; fields: ['id', 'request_source', 'input_calendar_type', 'solar_datetime_iso', 'lunar_datetime_text', 'gender', 'eight_char_provider_sect', 'normalized_timezone_offset_minutes', 'normalized_solar_datetime_utc', 'status', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'computed', 'failed']
  - constraint: CHECK (gender IN (0,1))
  - constraint: CHECK (eight_char_provider_sect IN (1,2))
  - constraint: CHECK (input_calendar_type IN ('solar','lunar'))
  - constraint: CHECK ((input_calendar_type='solar' AND solar_datetime_iso IS NOT NULL AND lunar_datetime_text IS NULL) OR (input_calendar_type='lunar' AND lunar_datetime_text IS NOT NULL AND solar_datetime_iso IS NULL))
- `bazi_charts.json` — Computed BaZi result for a request, including the four pillars and commonly returned detailed structures (stems/branches, five elements, ten gods, luck cycles etc.) stored as JSON. Serves getBaziDetail/buildBaziFromSolarDatetime/buildBaziFromLunarDatetime outputs and provides the canonical bazi string for reverse lookup indexing. (20 rows; fields: ['id', 'bazi_request_id', 'bazi_text', 'year_pillar', 'month_pillar', 'day_pillar', 'hour_pillar', 'detail_payload', 'computed_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded']
  - constraint: FOREIGN KEY (bazi_request_id) REFERENCES bazi_requests(id) ON DELETE CASCADE
  - constraint: UNIQUE (bazi_request_id)
  - constraint: UNIQUE (bazi_text)
  - constraint: CHECK (bazi_text ~ '^[^ ]+ [^ ]+ [^ ]+ [^ ]+$')
- `bazi_reverse_solar_times.json` — Reverse-lookup index mapping a BaZi (four pillars) to one or more candidate solar datetimes that produce that BaZi. Powers getSolarTimes. Generated offline or on-demand from ephemeris/calendar algorithms; stored to serve fast queries. (18 rows; fields: ['id', 'bazi_text', 'solar_datetime_text', 'solar_datetime_utc', 'default_timezone', 'confidence', 'source', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated']
  - constraint: CHECK (confidence >= 0 AND confidence <= 1)
  - constraint: CHECK (bazi_text ~ '^[^ ]+ [^ ]+ [^ ]+ [^ ]+$')
  - constraint: UNIQUE (bazi_text, solar_datetime_text, default_timezone)
  - constraint: INDEX (bazi_text)
- `calendar_requests.json` — Requests for Chinese calendar (Huangli) information for a given solar datetime (or default 'today' if omitted). Serves getChineseCalendar and enables caching/auditing of responses. (18 rows; fields: ['id', 'solar_datetime_iso', 'effective_solar_date', 'default_timezone', 'status', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'computed', 'failed']
  - constraint: CHECK (effective_solar_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
  - constraint: UNIQUE (COALESCE(solar_datetime_iso,''), default_timezone, effective_solar_date)
- `calendar_days.json` — Computed Huangli/Chinese calendar output for a specific effective solar date and timezone. Returned by getChineseCalendar; can be referenced by calendar_requests for caching. (19 rows; fields: ['id', 'effective_solar_date', 'default_timezone', 'huangli_payload', 'computed_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded']
  - constraint: CHECK (effective_solar_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
  - constraint: UNIQUE (effective_solar_date, default_timezone, status) WHERE status='active'

## Business rules enforced by the tools

- getBaziDetail must reject requests where both solarDatetime and lunarDatetime are provided or both are omitted; exactly one must be present.
- buildBaziFromSolarDatetime must require solarDatetime and must store input_calendar_type='solar'; buildBaziFromLunarDatetime must require lunarDatetime and must store input_calendar_type='lunar'.
- gender must be either 0 or 1; eightCharProviderSect must be either 1 or 2 (default 2 when omitted).
- When a BaZi computation succeeds, bazi_requests.status transitions from queued -> computed and a single bazi_charts row must exist with UNIQUE(bazi_request_id). On failure, bazi_requests.status transitions to failed and bazi_charts must not be created.
- bazi_charts.bazi_text must be exactly four whitespace-separated pillars and must equal CONCAT(year_pillar,' ',month_pillar,' ',day_pillar,' ',hour_pillar).
- getSolarTimes must lookup by exact bazi_text match; it returns bazi_reverse_solar_times rows where status='active', ordered by confidence desc then time asc; if none exist, the service may generate on-demand rows with source='on_demand'.
- getChineseCalendar with no solarDatetime must resolve to 'today' in the service default timezone and persist calendar_requests.effective_solar_date accordingly.
- For any (effective_solar_date, default_timezone), at most one calendar_days row may be active; recomputation must mark the previous row as superseded before inserting a new active row.
- All FK references must be enforced (bazi_charts.bazi_request_id must exist); deleting a bazi_request must cascade delete its bazi_chart.