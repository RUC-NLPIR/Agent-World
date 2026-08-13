# Yahoo Finance Server — local MCP environment

This backend powers a Yahoo Finance-backed data API that serves stock metadata, time-series OHLCV history, corporate actions, news, financial statements, holders, options, and analyst recommendations. The main workflows are: normalize a ticker into a tracked security, fetch/refresh data from Yahoo Finance into cached snapshots, and serve reads from cache with controlled TTL and request logging for quota/abuse protection.

Repository: https://github.com/hwangwoohyun-nav/yahoo-finance-mcp
Homepage: https://smithery.ai/server/@hwangwoohyun-nav/yahoo-finance-mcp

## Datastore

- `api_clients.json` — Represents an API consumer (service key) and its quota/limits. Used to authenticate/authorize requests and enforce rate limits. (12 rows; fields: ['id', 'name', 'api_key_hash', 'status', 'requests_per_minute_limit', 'requests_per_day_limit', 'current_day', 'requests_today', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(api_key_hash)
  - constraint: unique(name)
  - constraint: requests_per_minute_limit >= 1
  - constraint: requests_per_day_limit >= 1
- `securities.json` — Normalized security master keyed by Yahoo Finance ticker symbol. Stores stable identifiers and basic company/security attributes needed across endpoints. (31 rows; fields: ['id', 'ticker', 'exchange', 'quote_type', 'short_name', 'long_name', 'currency', 'country', 'sector', 'industry', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'delisted', 'unknown']
  - constraint: unique(lower(ticker))
  - constraint: ticker length between 1 and 16
- `finance_requests.json` — Immutable request log for all tool calls. Stores parameters, cache outcome, and links to any stored snapshots. Used for observability, quota enforcement, and debugging. (34 rows; fields: ['id', 'api_client_id', 'security_id', 'tool_name', 'ticker', 'parameters', 'status', 'http_status_code', 'error_code', 'error_message', 'cache_key', 'response_snapshot_id', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'served_from_cache', 'fetched_from_yahoo', 'failed']
  - constraint: duration_ms >= 0
  - constraint: http_status_code between 100 and 599 when not null
  - constraint: ticker length between 1 and 16
- `finance_snapshots.json` — Cached Yahoo Finance responses, normalized by security and dataset type. Stores either structured JSON data or pointer metadata plus freshness/TTL. (36 rows; fields: ['id', 'security_id', 'dataset', 'params_fingerprint', 'source', 'status', 'as_of', 'ttl_seconds', 'expires_at', 'payload', 'payload_schema_version', 'upstream_etag', 'upstream_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'expired', 'error']
  - constraint: unique(security_id, dataset, params_fingerprint)
  - constraint: ttl_seconds between 30 and 2592000
  - constraint: payload_schema_version >= 1
- `ohlcv_bars.json` — Normalized historical OHLCV bars for securities. Supports get_historical_stock_prices with period+interval reads without parsing large JSON blobs. (30 rows; fields: ['id', 'security_id', 'interval', 'bar_time', 'open', 'high', 'low', 'close', 'adj_close', 'volume', 'created_at', 'updated_at'])
  - lifecycle `interval`: ['1m', '2m', '5m', '15m', '30m', '60m', '90m', '1h', '1d', '5d', '1wk', '1mo', '3mo']
  - constraint: unique(security_id, interval, bar_time)
  - constraint: open is null or open >= 0
  - constraint: high is null or high >= 0
  - constraint: low is null or low >= 0

## Business rules enforced by the tools

- All tools must resolve the input ticker by case-insensitive match to securities.ticker; if not found, create a securities row with status='unknown' and then attempt upstream fetch; if upstream indicates invalid/delisted, transition to inactive or delisted accordingly.
- Every tool invocation must write exactly one finance_requests row with tool_name matching the invoked tool and parameters containing all supplied tool parameters; finance_requests.ticker must equal the user-supplied ticker string.
- Requests must be rejected (and logged with finance_requests.status='failed' and http_status_code=429) when api_clients.status != 'active' OR requests_today >= requests_per_day_limit OR per-minute rate limit would be exceeded.
- Snapshot lookup must use (security_id, dataset, params_fingerprint). If a snapshot exists with status='fresh' and expires_at > now(), serve from it and set finance_requests.status='served_from_cache'. Otherwise fetch upstream, upsert the snapshot, and set finance_requests.status='fetched_from_yahoo'.
- params_fingerprint must be computed deterministically from tool parameters relevant to that dataset: historical_prices uses (period, interval); financial_statement uses (financial_type); holder_info uses (holder_type); option_chain uses (expiration_date, option_type); recommendations uses (recommendation_type, months_back). Tools with only ticker use an empty/constant fingerprint value (e.g., 'default').
- get_historical_stock_prices(period) must only accept period in {1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max}; otherwise return 400 and do not create/update ohlcv_bars, but still log the request as failed.
- get_historical_stock_prices(interval) must be a supported interval enum; on successful upstream fetch, returned bars must be upserted into ohlcv_bars keyed by (security_id, interval, bar_time).
- get_option_chain must validate expiration_date format 'YYYY-MM-DD' and option_type in {'calls','puts'}; invalid inputs return 400 and are logged as failed.
- get_financial_statement must validate financial_type in {'income_stmt','quarterly_income_stmt','balance_sheet','quarterly_balance_sheet','cashflow','quarterly_cashflow'}; invalid values return 400 and are logged as failed.
- get_holder_info must validate holder_type in {'major_holders','institutional_holders','mutualfund_holders','insider_transactions','insider_purchases','insider_roster_holders'}; invalid values return 400 and are logged as failed.
- get_recommendations must validate months_back between 1 and 60 (inclusive); if omitted, default to 12 and store that defaulted value in finance_requests.parameters.