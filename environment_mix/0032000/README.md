# Alpha Vantage Financial Data Server — local MCP environment

This backend powers an Alpha Vantage proxy/data server that fetches market data (equities, FX, crypto) and technical indicators, then caches normalized results for fast repeated reads. Core workflows: accept a data request (tool call), enforce API key quotas, fetch from Alpha Vantage when cache is stale, store responses as snapshots plus optional normalized time-series points, and return the latest snapshot to the caller.

Repository: https://github.com/deepsuthar496/alpha-ventage-mcp
Homepage: https://smithery.ai/server/@deepsuthar496/alpha-ventage-mcp

## Datastore

- `api_keys.json` — Client API keys that authenticate callers to this server and enforce per-key usage quotas and rate limits. (25 rows; fields: ['id', 'key_hash', 'label', 'status', 'plan', 'quota_daily_requests', 'quota_minute_requests', 'quota_daily_vendor_calls', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: quota_daily_requests >= 0
  - constraint: quota_minute_requests >= 0
  - constraint: quota_daily_vendor_calls >= 0
- `assets.json` — Canonical instruments and currency/crypto identifiers used by requests and cached data (equity tickers, FX currencies, crypto symbols). (30 rows; fields: ['id', 'asset_type', 'symbol', 'market', 'name', 'currency', 'status', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: unique(asset_type, symbol, market)
  - constraint: symbol != ''
  - constraint: asset_type in ('equity','forex_currency','crypto')
- `data_requests.json` — Each tool invocation recorded as a request with normalized parameters, used for auditing, deduping, cache lookup, and quota enforcement. (31 rows; fields: ['id', 'api_key_id', 'tool_name', 'asset_id', 'base_currency_asset_id', 'quote_currency_asset_id', 'indicator', 'interval', 'time_period', 'series_type', 'outputsize', 'vendor_function', 'request_fingerprint', 'status', 'http_status', 'error_code', 'error_message', 'vendor_call_count', 'response_snapshot_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'fetching', 'served_from_cache', 'succeeded', 'failed', 'rate_limited']
  - constraint: foreign key(api_key_id) references api_keys(id)
  - constraint: foreign key(asset_id) references assets(id)
  - constraint: foreign key(base_currency_asset_id) references assets(id)
  - constraint: foreign key(quote_currency_asset_id) references assets(id)
- `response_snapshots.json` — Cached vendor responses and server-normalized payloads keyed by request fingerprint; used to serve read tools quickly and to reduce vendor calls. (37 rows; fields: ['id', 'request_fingerprint', 'tool_name', 'asset_id', 'base_currency_asset_id', 'quote_currency_asset_id', 'vendor_function', 'vendor_raw_json', 'normalized_json', 'status', 'expires_at', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'invalid']
  - constraint: unique(request_fingerprint, tool_name)
  - constraint: foreign key(asset_id) references assets(id)
  - constraint: foreign key(base_currency_asset_id) references assets(id)
  - constraint: foreign key(quote_currency_asset_id) references assets(id)
- `timeseries_points.json` — Normalized OHLCV and derived indicator datapoints extracted from response snapshots for time-series tools (daily/weekly) and technical indicators. (33 rows; fields: ['id', 'response_snapshot_id', 'asset_id', 'series_kind', 'timestamp', 'open', 'high', 'low', 'close', 'volume', 'indicator', 'indicator_value', 'indicator_values', 'base_currency_asset_id', 'quote_currency_asset_id', 'rate', 'price', 'created_at', 'updated_at'])
  - lifecycle `series_kind`: ['daily_ohlcv', 'weekly_ohlcv', 'technical_indicator', 'fx_rate', 'crypto_price']
  - constraint: foreign key(response_snapshot_id) references response_snapshots(id)
  - constraint: foreign key(asset_id) references assets(id)
  - constraint: foreign key(base_currency_asset_id) references assets(id)
  - constraint: foreign key(quote_currency_asset_id) references assets(id)

## Business rules enforced by the tools

- Every tool call must create exactly one data_requests row tied to an active api_keys row; if api_keys.status != 'active', the request must end in status='rate_limited' or 'failed' and vendor_call_count must be 0.
- A request is eligible to be served from cache when a response_snapshots row exists for the same (tool_name, request_fingerprint) with status='fresh' and (expires_at is null or expires_at > now()). In this case, data_requests.status must transition to 'served_from_cache' then 'succeeded' and vendor_call_count must be 0.
- If cache is missing or stale, the server must transition data_requests.status from 'queued' -> 'fetching', perform the vendor call, upsert a response_snapshots row for (tool_name, request_fingerprint), set fetched_at=now(), set expires_at based on per-tool TTL policy, and then set data_requests.status='succeeded' with vendor_call_count >= 1.
- Daily/minute quotas must be enforced per api_key_id: the count of data_requests created within the window cannot exceed quota_daily_requests/quota_minute_requests; if exceeded, the request must end status='rate_limited' with http_status=429 and vendor_call_count=0.
- Upstream vendor call quotas must be enforced per api_key_id: sum(vendor_call_count) over a UTC day cannot exceed quota_daily_vendor_calls; exceeding it must produce status='rate_limited' and must not call the vendor.
- Tool-to-parameter integrity: get_forex_rate requires base_currency_asset_id and quote_currency_asset_id (and they must reference assets.asset_type='forex_currency'); get_stock_price/get_company_overview/get_daily_time_series/get_weekly_time_series require asset_id referencing assets.asset_type='equity'; get_crypto_price requires asset_id referencing assets.asset_type='crypto'; get_technical_indicator requires asset_id (equity) plus indicator and interval.
- When parsing time series responses, the server may populate timeseries_points for daily/weekly/technical data. All points must reference an existing response_snapshots row and must be unique per (response_snapshot_id, series_kind, timestamp, indicator).
- Status transitions must follow the declared lifecycles; direct transitions not listed (e.g., queued->succeeded) are invalid and must be rejected by application logic/tests.