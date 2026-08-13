# Financial Modeling Prep (FMP) Server — local MCP environment

This backend stores a normalized reference catalog of financial instruments (equities, ETFs/funds, forex pairs, crypto pairs, commodities, indexes), their issuing entities (companies/registrants) and exchanges, plus time-series market data (EOD/intraday), fundamental filings-derived facts (financial statements, ratios/metrics), corporate actions/events, news, and a lightweight API access layer (API keys + request/usage logs). Workflows: ingest/refresh reference and time-series data from upstream feeds/SEC, serve high-volume read endpoints with filtering/pagination, and enforce per-key quotas while logging request activity for analytics and billing.

Repository: https://github.com/imbenrabi/Financial-Modeling-Prep-MCP-Server
Homepage: https://smithery.ai/server/@imbenrabi/financial-modeling-prep-mcp-server

## Datastore

- `api_keys.json` — API credentials, quota policy and lifecycle for clients calling the service. Used to authorize/track all tool calls and enforce rate/usage limits. (33 rows; fields: ['id', 'key_hash', 'label', 'status', 'plan', 'daily_request_quota', 'minute_request_quota', 'concurrency_limit', 'allowed_exchanges', 'allowed_asset_types', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: daily_request_quota >= 0
  - constraint: minute_request_quota >= 0
  - constraint: concurrency_limit >= 0
- `request_logs.json` — Immutable request/response metadata for every tool call, used for auditing, debugging, usage and quota enforcement. (19 rows; fields: ['id', 'api_key_id', 'tool_name', 'params', 'http_status', 'cache_status', 'duration_ms', 'result_count', 'error_code', 'created_at', 'updated_at'])
  - lifecycle `cache_status`: ['hit', 'miss', 'bypass']
  - constraint: http_status between 100 and 599
  - constraint: duration_ms >= 0
  - constraint: result_count is null or result_count >= 0
  - constraint: FK(api_key_id) references api_keys.id on delete restrict
- `entities.json` — Issuer/registrant and other real-world entities (public companies, funds, institutions, politicians) identified by CIK and names. Supports CIK/name search tools and SEC-profile tools. (18 rows; fields: ['id', 'entity_type', 'name', 'normalized_name', 'cik', 'sic_code', 'sic_industry_title', 'country', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'merged']
  - constraint: unique(cik) where cik is not null
  - constraint: unique(entity_type, normalized_name)
  - constraint: length(normalized_name) > 0
- `instruments.json` — Master catalog of tradable instruments (stocks, ETFs, mutual funds, indexes, crypto pairs, forex pairs, commodities) with symbol, exchange and classification flags. Drives symbol searches, screeners, lists, variants and many quote/chart tools. (18 rows; fields: ['id', 'symbol', 'normalized_symbol', 'name', 'asset_type', 'exchange', 'currency', 'country', 'sector', 'industry', 'entity_id', 'is_etf', 'is_fund', 'is_actively_trading', 'is_delisted', 'primary_listing_symbol_id', 'share_class_code', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'delisted']
  - constraint: unique(normalized_symbol, exchange) where exchange is not null
  - constraint: unique(normalized_symbol) where exchange is null
  - constraint: is_etf implies asset_type in ('etf')
  - constraint: is_fund implies asset_type in ('mutual_fund','etf')
- `market_data_points.json` — Unified time-series store for quotes and chart data across all instrument types. Supports EOD light/full charts, intraday 1min/5min/15min/30min/1hour/4hour, and snapshot quotes (latest row per instrument+timeframe). (17 rows; fields: ['id', 'instrument_id', 'timeframe', 'ts', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'vwap', 'change', 'change_percent', 'adjustment_type', 'session', 'is_latest_snapshot', 'created_at', 'updated_at'])
  - lifecycle `session`: ['regular', 'aftermarket']
  - constraint: unique(instrument_id, timeframe, ts, adjustment_type, session)
  - constraint: open is null or open >= 0
  - constraint: high is null or high >= 0
  - constraint: low is null or low >= 0
- `content_items.json` — Unified store for non-price content and derived analytics: news/articles/press releases, corporate actions & calendars, SEC filings metadata, analyst grades/price targets, ESG, economic/treasury indicators, and computed technical indicators. Supports the many 'latest', 'search', 'calendar', and 'bulk' tools via typed records with JSON payloads and common filtering columns. (20 rows; fields: ['id', 'content_type', 'instrument_id', 'entity_id', 'exchange', 'sector', 'industry', 'as_of_date', 'from_date', 'to_date', 'period', 'year', 'quarter', 'identifier_1', 'identifier_2', 'title', 'url', 'payload', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded', 'deleted']
  - constraint: FK(instrument_id) references instruments.id on delete set null
  - constraint: FK(entity_id) references entities.id on delete set null
  - constraint: quarter is null or (quarter >= 1 and quarter <= 4)
  - constraint: year is null or (year >= 1900 and year <= 2200)

## Business rules enforced by the tools

- All tool invocations must authenticate with an api_keys record in status='active'; otherwise return an authorization error and still log the attempt with http_status=401/403.
- For every request, write exactly one request_logs row; request_logs.params must conform to the tool JSON schema (no additionalProperties).
- Pagination parameters page/limit must be enforced: page >= 0; limit defaults per tool; limit must not exceed tool-stated max (e.g., 1000/5000/10000/250).
- Date filters from/to must be valid ISO dates (YYYY-MM-DD) and must satisfy from <= to when both provided.
- Symbol inputs are matched against instruments.normalized_symbol; for tools with an exchange parameter, apply (normalized_symbol, exchange) uniqueness semantics.
- searchSymbol/searchName/searchCompaniesByName/searchFundDisclosures and similar 'query/name/company' searches must use normalized matching on entities.normalized_name and/or instruments.name with a result cap of limit (default per tool).
- stockScreener filters must be applied over the latest available fundamental/market snapshot by joining instruments to latest market_data_points (is_latest_snapshot=true, timeframe='1day', session='regular') and to relevant content_items (e.g., key_metrics/ratios) where needed; includeAllShareClasses=false must exclude instruments with primary_listing_symbol_id not null unless explicitly requested.
- getQuote/getQuoteShort/getExchangeQuotes and batch quote tools must return the latest unadjusted regular-session snapshot from market_data_points; aftermarket tools must return the latest unadjusted aftermarket snapshot.
- Chart tools (light/full/unadjusted/dividendAdjusted/intraday) must read from market_data_points with matching timeframe and adjustment_type; when from/to are omitted, return the provider default window but never exceed server-side max rows per response.
- CIK-based tools must resolve entities by entities.cik; if multiple entities share a CIK, this violates unique(cik) and must be prevented at write time.
- Tools that accept comma-separated symbols must split, normalize, de-duplicate, and enforce a maximum list length (server policy) before querying.
- Bulk endpoints that accept year/period/part must validate year/period/part and serve from content_items where content_type matches (e.g., financial_statement for getIncomeStatementsBulk) and payload contains the bulk rows; if part is used, it must partition deterministically (e.g., hash(normalized_symbol) mod N == part).
- Status transitions must be enforced as declared: api_keys.revoked is terminal; entities.merged is terminal; instruments.delisted is terminal; content_items.deleted is terminal.
- Quota enforcement: if a request would exceed api_keys.minute_request_quota or api_keys.daily_request_quota, reject with 429 and log it; quota counters are computed from request_logs over rolling windows.