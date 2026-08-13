# CCXT MCP Server — local MCP environment

This backend powers an MCP server that wraps CCXT to query public market data (tickers, orderbooks, trades, OHLCV, markets) and to perform authenticated trading actions (balances, orders, leverage, margin mode) across many exchanges. It also persists server runtime configuration (log level, proxy, default market type) and tracks an internal cache plus per-call request logs to support cache stats/clearing and operational debugging.

Repository: https://github.com/doggybee/mcp-server-ccxt
Homepage: https://smithery.ai/server/@doggybee/mcp-server-ccxt

## Datastore

- `server_settings.json` — Singleton-like persisted runtime configuration for the CCXT MCP server (log level, default market type, proxy settings) used by all tools. Mutated by set-log-level, set-proxy-config, set-market-type; read by get-proxy-config. (12 rows; fields: ['id', 'scope', 'status', 'log_level', 'default_market_type', 'proxy_enabled', 'proxy_url', 'proxy_username', 'proxy_password_encrypted', 'proxy_last_test_exchange_id', 'proxy_last_test_at', 'proxy_last_test_status', 'proxy_last_test_error', 'updated_by_tool', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'updating', 'error']
  - constraint: unique(scope)
  - constraint: proxy_enabled IN (true,false)
  - constraint: proxy_url <> ''
  - constraint: proxy_enabled = false OR proxy_url LIKE 'http%://%'
- `exchanges.json` — Catalog of CCXT-supported exchanges and high-level capability metadata. Used by list-exchanges, get-exchange-info, get-market-types, and as FK targets for market data/trading logs. (31 rows; fields: ['id', 'exchange_code', 'display_name', 'status', 'supported_market_types', 'has_private_api', 'rate_limit_ms', 'last_info_refresh_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['enabled', 'disabled', 'degraded']
  - constraint: unique(exchange_code)
  - constraint: exchange_code <> ''
  - constraint: display_name <> ''
  - constraint: has_private_api IN (true,false)
- `ccxt_cache_entries.json` — Materialized cache of CCXT responses and derived market data to support cache-stats, clear-cache, clear-exchange-cache, and to reduce upstream calls for public data tools. (39 rows; fields: ['id', 'exchange_id', 'market_type', 'resource_type', 'symbol', 'symbols', 'timeframe', 'limit', 'page', 'page_size', 'cache_key', 'status', 'ttl_seconds', 'expires_at', 'hit_count', 'last_hit_at', 'payload', 'payload_bytes', 'created_at', 'updated_at'])
  - lifecycle `status`: ['valid', 'stale', 'invalidated']
  - constraint: foreign key (exchange_id) references exchanges(id) on delete cascade
  - constraint: unique(cache_key)
  - constraint: ttl_seconds BETWEEN 1 AND 86400
  - constraint: payload_bytes >= 0
- `exchange_credentials.json` — Encrypted storage of user-supplied exchange credentials keyed by exchange and API key fingerprint to avoid persisting raw secrets in request logs. Used to back authenticated tools (account-balance, place-market-order, place-futures-market-order, set-leverage, set-margin-mode). (34 rows; fields: ['id', 'exchange_id', 'api_key_fingerprint', 'api_key_last4', 'api_key_encrypted', 'secret_encrypted', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: foreign key (exchange_id) references exchanges(id) on delete cascade
  - constraint: unique(exchange_id, api_key_fingerprint)
  - constraint: api_key_fingerprint <> ''
- `ccxt_requests.json` — Audit log of tool invocations and outcomes across public/private methods, including parameters (redacted), cache behavior, and errors. Supports operational debugging, cache-stats, and validates that mutating tools (orders/leverage/margin) were executed. (36 rows; fields: ['id', 'tool_name', 'exchange_id', 'credential_id', 'market_type', 'symbol', 'symbols', 'timeframe', 'limit', 'page', 'page_size', 'side', 'amount', 'leverage', 'margin_mode', 'extra_params', 'cache_action', 'cache_entry_id', 'status', 'http_status', 'duration_ms', 'error_code', 'error_message', 'response_summary', 'created_at', 'updated_at'])
  - lifecycle `status`: ['success', 'error']
  - constraint: foreign key (exchange_id) references exchanges(id)
  - constraint: foreign key (credential_id) references exchange_credentials(id)
  - constraint: foreign key (cache_entry_id) references ccxt_cache_entries(id)
  - constraint: duration_ms >= 0

## Business rules enforced by the tools

- For any tool parameter named exchange, the value must map to an exchanges.exchange_code with status != 'disabled'; otherwise the request must be recorded in ccxt_requests with status='error' and error_code='EXCHANGE_NOT_FOUND' or 'EXCHANGE_DISABLED'.
- When a tool call omits marketType, the server must resolve market_type from server_settings.default_market_type and persist the resolved value in ccxt_requests.market_type.
- set-log-level must update server_settings.log_level and set server_settings.updated_by_tool='set-log-level'. It must only accept levels in {debug,info,warning,error}.
- set-market-type must update server_settings.default_market_type and, if clearCache=true, invalidate all ccxt_cache_entries by setting status='invalidated' and record a ccxt_requests row with cache_action='cleared'.
- set-proxy-config must require enabled and url; if enabled=true then url must be a non-empty http(s) URL. If clearCache=true it must invalidate all ccxt_cache_entries and record the action in ccxt_requests.cache_action='cleared'.
- get-proxy-config must return values from server_settings (proxy_enabled, proxy_url, proxy_username) and must never return proxy_password_encrypted in any response.
- clear-cache must delete or invalidate all ccxt_cache_entries and create a ccxt_requests row with tool_name='clear-cache' and cache_action='cleared'.
- clear-exchange-cache must invalidate all ccxt_cache_entries (since tool surface has no exchange parameter) and record tool_name='clear-exchange-cache' with cache_action='cleared'.
- cache-stats must compute stats from ccxt_cache_entries (counts by status/resource_type, total payload_bytes, total hit_count) and should include oldest/newest created_at; it must not require any parameters.
- Public market data tools (get-ticker, batch-get-tickers, get-orderbook, get-ohlcv, get-trades, get-markets, get-exchange-info, get-leverage-tiers, get-funding-rates, get-market-types) must attempt to serve from ccxt_cache_entries when a valid unexpired entry exists; on cache hit, increment hit_count and set last_hit_at.
- get-ohlcv limit must be clamped to max 1000; values above 1000 must be rejected or coerced and the effective limit stored in ccxt_requests.limit.
- get-orderbook limit, get-trades limit, get-markets page/pageSize must be validated as positive integers; invalid values must produce ccxt_requests.status='error' with error_code='INVALID_ARGUMENT'.
- Authenticated tools (account-balance, place-market-order, place-futures-market-order, set-leverage, set-margin-mode) must not persist raw apiKey/secret in ccxt_requests; instead they must upsert exchange_credentials by (exchange_id, api_key_fingerprint) and reference it via ccxt_requests.credential_id.
- place-market-order and place-futures-market-order must require amount > 0 and side in {buy,sell}. The request must be logged even if the upstream exchange rejects it.
- set-leverage must require marketType in {future,swap} (default future) and leverage > 0; set-margin-mode must require marginMode in {cross,isolated} and marketType in {future,swap}.
- test-proxy-connection must attempt a lightweight call for the specified exchange and update server_settings.proxy_last_test_* fields; it must also create a ccxt_requests row with tool_name='test-proxy-connection'.
- list-exchanges must be backed by exchanges rows and should return exchange_code/display_name; disabled exchanges may be included but should be identifiable via status.
- get-markets pagination must be implemented as page/pageSize over a cached 'markets' payload per exchange+market_type+page+page_size; if pageSize is not provided, default 100.
- Any cache key must be deterministic: cache_key = hash(exchange_code, market_type, resource_type, symbol, symbols, timeframe, limit, page, page_size) and unique across ccxt_cache_entries.