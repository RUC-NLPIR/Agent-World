# Spreadsheet MCP Server — local MCP environment

This backend stores references to Google Spreadsheets by URL, their discovered metadata (spreadsheet identity, title), the list of sheets within each spreadsheet, and cached cell data snapshots for sheets. The main workflows are: resolve a spreadsheet by URL, return its basic info plus sheet list; and fetch a specific sheet's data (optionally served from cache) by spreadsheet URL + sheet name.

Repository: https://github.com/HosakaKeigo/spreadsheet-mcp-server
Homepage: https://smithery.ai/server/@HosakaKeigo/spreadsheet-mcp-server

## Datastore

- `spreadsheets.json` — Canonical spreadsheet records resolved from a provided URL (e.g., Google Sheets). Stores normalized spreadsheet identity and basic metadata used by getSpreadsheet/getSheetData. (18 rows; fields: ['id', 'provider', 'url', 'normalized_url', 'external_spreadsheet_id', 'title', 'locale', 'timezone', 'status', 'last_synced_at', 'last_error_code', 'last_error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'restricted', 'not_found', 'error', 'archived']
  - constraint: unique(provider, normalized_url)
  - constraint: unique(provider, external_spreadsheet_id)
  - constraint: status in ('active','restricted','not_found','error','archived')
  - constraint: normalized_url <> ''
- `sheets.json` — Sheets (tabs) contained in a spreadsheet. Used to return the sheet list for getSpreadsheet and to resolve sheetName for getSheetData. (17 rows; fields: ['id', 'spreadsheet_id', 'external_sheet_id', 'name', 'index', 'row_count', 'column_count', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'hidden', 'error']
  - constraint: foreign key (spreadsheet_id) references spreadsheets(id) on delete cascade
  - constraint: unique(spreadsheet_id, name)
  - constraint: external_sheet_id is null or external_sheet_id >= 0
  - constraint: row_count is null or row_count >= 0
- `sheet_data_snapshots.json` — Cached data snapshots for a sheet. Allows getSheetData to return data quickly and provides an audit trail of what data was fetched when. (17 rows; fields: ['id', 'spreadsheet_id', 'sheet_id', 'range_a1', 'major_dimension', 'values', 'row_count', 'column_count', 'etag', 'fetched_at', 'status', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'error']
  - constraint: foreign key (spreadsheet_id) references spreadsheets(id) on delete cascade
  - constraint: foreign key (sheet_id) references sheets(id) on delete cascade
  - constraint: row_count >= 0
  - constraint: column_count >= 0
- `spreadsheet_access_logs.json` — Immutable access log for tool calls. Supports debugging, rate limiting, and tracing failures when resolving url or sheetName. (18 rows; fields: ['id', 'tool_name', 'request_url', 'request_sheet_name', 'spreadsheet_id', 'sheet_id', 'response_status', 'provider_latency_ms', 'cache_hit', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `response_status`: ['ok', 'not_found', 'restricted', 'invalid_argument', 'error']
  - constraint: tool_name in ('getSpreadsheet','getSheetData')
  - constraint: provider_latency_ms is null or provider_latency_ms >= 0
  - constraint: cache_hit in (true,false)
  - constraint: If tool_name = 'getSheetData' then request_sheet_name is not null

## Business rules enforced by the tools

- getSpreadsheet(url) must resolve spreadsheets by normalized_url; if not present, insert a spreadsheets row with provider='google_sheets', url, normalized_url, external_spreadsheet_id parsed from url, status='active' only after a successful provider metadata fetch; otherwise set status to 'restricted'|'not_found'|'error' based on provider response.
- getSpreadsheet(url) response must be derived from spreadsheets plus sheets where sheets.spreadsheet_id matches and sheets.status != 'deleted'.
- getSheetData(url, sheetName) must resolve spreadsheets by normalized_url, then resolve sheets by (spreadsheet_id, name); if no matching sheet with status in ('active','hidden') exists, return not_found and log it.
- getSheetData(url, sheetName) may serve from the newest sheet_data_snapshots row for the resolved sheet with status='fresh'; if no fresh snapshot exists (or it is older than a configured TTL), fetch from provider and create a new snapshot marked fresh, and mark older fresh snapshots as stale.
- A sheet name must be unique within a spreadsheet: enforce unique(spreadsheet_id, name).
- Foreign key integrity must be enforced: sheets.spreadsheet_id must exist; sheet_data_snapshots must reference existing spreadsheets and sheets; deleting a spreadsheet must cascade delete its sheets and snapshots.
- Row and column counts in snapshots must match values: row_count equals length(values); column_count equals max(length(values[i])) (treat missing rows as 0).
- All tool invocations must append an access log row with tool_name, request_url, request_sheet_name (if applicable), resolution ids (if any), response_status, and cache_hit; logs are immutable after creation.