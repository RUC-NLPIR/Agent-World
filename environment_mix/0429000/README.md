# Binance Cryptocurrency Market Data Service — local MCP environment

This backend brokers and caches Binance spot market-data responses for trading symbols (e.g., BTCUSDT), enforcing per-client API key quotas and capturing request/response audit trails. Core workflows: validate an incoming tool call, record a request, optionally serve from cache, fetch from Binance if needed, store normalized snapshots (order book, trades, klines, tickers), and return the latest view for the requested symbol(s) and parameters.

Repository: https://github.com/snjyor/binance-mcp
Homepage: https://smithery.ai/server/@snjyor/binance-mcp-data

## Datastore

- `api_keys.json` — Client credentials used to access this service, including quotas and status. Every tool call is associated to exactly one api_key and is rate/usage limited by its plan fields. (29 rows; fields: ['id', 'key_hash', 'name', 'status', 'default_cache_ttl_ms', 'rpm_limit', 'daily_request_limit', 'max_symbols_per_request', 'created_at', 'updated_at', 'revoked_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(name)
  - constraint: default_cache_ttl_ms >= 0
  - constraint: rpm_limit >= 1
- `symbols.json` — Canonical trading symbols supported by the service and their base/quote assets. Used to validate tool parameters like symbol and symbols[]. (32 rows; fields: ['id', 'symbol', 'base_asset', 'quote_asset', 'status', 'min_price_increment', 'min_qty_increment', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'delisted']
  - constraint: unique(symbol)
  - constraint: length(symbol) between 5 and 20
  - constraint: min_price_increment is null or min_price_increment > 0
  - constraint: min_qty_increment is null or min_qty_increment > 0
- `requests.json` — Immutable audit log of every tool call with normalized parameters, cache decision, upstream fetch info, and error state. Serves analytics, debugging, and quota enforcement. (38 rows; fields: ['id', 'api_key_id', 'tool_name', 'status', 'symbol_id', 'symbols', 'interval', 'start_time_ms', 'end_time_ms', 'time_zone', 'time_zone_offset_minutes', 'from_id', 'limit', 'window_size', 'response_type', 'cache_key', 'cache_hit', 'upstream_http_status', 'error_code', 'error_message', 'latency_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'served_from_cache', 'fetched_upstream', 'failed', 'rejected']
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: fk(symbol_id) references symbols(id) on delete restrict
  - constraint: unique(cache_key, created_at) is not required; cache_key is not unique due to multiple calls
  - constraint: limit is null or limit between 1 and 5000 (order book max); tool-level validation further restricts per tool
- `market_data_cache.json` — Cached upstream responses keyed by tool + normalized params. Stores raw payload for fidelity plus minimal indexing fields. Used to serve read tools quickly and reduce upstream calls. (36 rows; fields: ['id', 'cache_key', 'tool_name', 'primary_symbol_id', 'symbols', 'interval', 'start_time_ms', 'end_time_ms', 'time_zone', 'time_zone_offset_minutes', 'from_id', 'limit', 'window_size', 'response_type', 'payload_json', 'payload_bytes', 'source', 'status', 'fetched_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'expired']
  - constraint: unique(cache_key)
  - constraint: fk(primary_symbol_id) references symbols(id) on delete restrict
  - constraint: payload_bytes >= 0
  - constraint: expires_at >= fetched_at
- `usage_counters.json` — Aggregated usage per api key and time bucket for enforcing rpm and daily limits and for billing/analytics. Updated transactionally as requests are accepted. (29 rows; fields: ['id', 'api_key_id', 'bucket_type', 'bucket_start', 'requests_total', 'requests_rejected', 'upstream_fetches', 'cache_hits', 'created_at', 'updated_at'])
  - lifecycle `bucket_type`: ['minute', 'day']
  - constraint: fk(api_key_id) references api_keys(id) on delete cascade
  - constraint: unique(api_key_id, bucket_type, bucket_start)
  - constraint: requests_total >= 0
  - constraint: requests_rejected >= 0

## Business rules enforced by the tools

- Every tool call must authenticate to an api_keys row with status = 'active'; otherwise a requests row is written with status='rejected' and error_code='API_KEY_INACTIVE'.
- For tools that accept 'symbol', the symbol string must exist in symbols.symbol with symbols.status='active'; otherwise reject with error_code='UNKNOWN_SYMBOL'.
- For tools that accept 'symbols' array, the array must be non-empty, contain no duplicates, contain at most api_keys.max_symbols_per_request entries, and every entry must exist and be active in symbols; otherwise reject.
- Mutual exclusivity: if 'symbol' is provided then 'symbols' must be null/omitted; if 'symbols' is provided then 'symbol' must be null/omitted (applies to get_24hr_ticker, get_trading_day_ticker, get_price, get_book_ticker, get_rolling_window_ticker).
- Limit validation per tool: get_order_book.limit must be between 1 and 5000; get_recent_trades.limit, get_historical_trades.limit, get_aggregate_trades.limit, get_klines.limit, get_ui_klines.limit must be between 1 and 1000 (default applied when omitted).
- fromId must be an integer >= 0 where present; if fromId is provided for get_historical_trades/get_aggregate_trades, results start at that id (encoded into cache_key).
- For get_aggregate_trades and kline tools: if both startTime and endTime are provided then endTime >= startTime; timestamps are milliseconds since epoch and must be >= 0.
- For get_klines and get_ui_klines: interval must be one of the allowed enum values; timeZone defaults to 'UTC' when omitted and is normalized into cache_key.
- For get_trading_day_ticker: timeZone is numeric in the tool surface; store it as time_zone_offset_minutes (default 0) and include in cache_key.
- For get_trading_day_ticker and get_rolling_window_ticker: type must be either FULL or MINI when provided; if omitted, service default is FULL and is normalized into cache_key.
- For get_rolling_window_ticker: windowSize must be provided or defaulted by the service; it is part of cache_key and affects cache segmentation.
- Cache lookup uses market_data_cache.cache_key; if exists and expires_at > now() and status in ('fresh','stale' where stale is allowed by policy), the request is served from cache and requests.status='served_from_cache' with cache_hit=true.
- On cache miss or expired entry, the service fetches from Binance, upserts market_data_cache by cache_key, sets fetched_at=now(), expires_at=now()+ttl, status='fresh', and records requests.status='fetched_upstream'.
- TTL selection: cache TTL is derived from api_keys.default_cache_ttl_ms but may be overridden by endpoint policy (e.g., order book shorter TTL than 24hr ticker); the chosen TTL must be >= 0.
- Quota enforcement: before processing an accepted request, increment usage_counters for (minute bucket) and (day bucket); if minute requests_total would exceed api_keys.rpm_limit or day requests_total would exceed api_keys.daily_request_limit, do not call upstream, and record requests.status='rejected'.
- Requests rows are append-only except status/latency/error fields; tool_name, normalized params, and cache_key must not change after initial insert.
- FK integrity: deleting an api_key cascades to usage_counters but must not delete historical requests (on delete restrict), preserving audit logs.