# AKShare One MCP Server — local MCP environment

This backend supports an MCP server that fetches market/financial data for equities by symbol from multiple upstream providers (eastmoney, sina, xueqiu), optionally computing technical indicators, and returns datasets such as historical bars, realtime quotes, news, financial statements, and insider trades. The core workflows are (1) resolving a requested symbol to a known instrument, (2) reading from a cache of normalized datasets when available, otherwise fetching from an upstream source and storing results, and (3) tracking each tool call for auditing, rate-limiting, and debugging.

Repository: https://github.com/zwldarren/akshare-one-mcp
Homepage: https://smithery.ai/server/@zwldarren/akshare-one-mcp

## Datastore

- `instruments.json` — Master data for tradable instruments addressed by the API via `symbol` (e.g. '000001'). Used to normalize symbol handling across A/B/H shares and link all cached datasets. (18 rows; fields: ['id', 'symbol', 'exchange', 'name', 'security_type', 'currency', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'delisted']
  - constraint: unique(symbol)
  - constraint: symbol length between 1 and 32
  - constraint: security_type in ('stock')
- `api_keys.json` — API keys used to authenticate and rate-limit callers of the MCP server; also anchors audit logs for each tool call. (18 rows; fields: ['id', 'key_hash', 'label', 'status', 'requests_per_minute', 'requests_per_day', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: requests_per_minute between 1 and 100000
  - constraint: requests_per_day between 1 and 100000000
- `tool_calls.json` — Audit and observability log for each tool invocation (e.g., get_hist_data). Stores request parameters, resolution to instrument, upstream source used, timing, and outcome. (19 rows; fields: ['id', 'api_key_id', 'tool_name', 'instrument_id', 'symbol', 'source', 'interval', 'interval_multiplier', 'start_date', 'end_date', 'adjust', 'indicators_list', 'recent_n', 'status', 'cache_hit', 'upstream_latency_ms', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed']
  - constraint: interval_multiplier is null or interval_multiplier >= 1
  - constraint: recent_n is null or recent_n >= 1
  - constraint: cache_hit in (true,false)
  - constraint: if tool_name = 'get_hist_data' then symbol is not null and interval is not null and interval_multiplier is not null and start_date is not null and end_date is not null and adjust is not null
- `market_data_cache.json` — Normalized cached datasets returned by tools. Stores historical OHLCV bars, realtime snapshots, news items, financial statement rows, cash flow rows, and insider trades. Payload is stored as JSON for flexibility across sources; indexed dimensions enable efficient lookups by tool parameters. (19 rows; fields: ['id', 'instrument_id', 'dataset_type', 'source', 'interval', 'interval_multiplier', 'adjust', 'start_date', 'end_date', 'indicators_list', 'as_of', 'ttl_seconds', 'status', 'payload', 'payload_row_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'expired']
  - constraint: ttl_seconds >= 0
  - constraint: payload_row_count >= 0
  - constraint: if dataset_type = 'hist_bars' then instrument_id is not null and source is not null and interval is not null and interval_multiplier is not null and adjust is not null and start_date is not null and end_date is not null
  - constraint: if dataset_type = 'realtime_quote' then instrument_id is null or instrument_id is not null

## Business rules enforced by the tools

- For any tool call that includes `symbol` (required or optional), the backend must resolve it to an instruments row (creating one with status='active' if absent) unless the tool is get_time_info or the client provided null symbol for get_realtime_data.
- get_hist_data must enforce: interval in {minute,hour,day,week,month,year}, interval_multiplier >= 1, adjust in {none,qfq,hfq}, and start_date <= end_date (lexical YYYY-MM-DD comparison).
- For tools with `recent_n`, the response must contain at most recent_n items/rows; recent_n must be null or >= 1. If recent_n is null, server default applies (hist: 100; news/financials: 10) and is recorded in tool_calls.recent_n.
- If indicators_list is provided for get_hist_data, every entry must be in {SMA,EMA,RSI,MACD,BOLL,STOCH,ATR,CCI,ADX}; computed indicator columns must be included in market_data_cache.payload for the hist_bars dataset variant keyed by indicators_list.
- Cache selection: when serving a request, choose the newest market_data_cache row whose dimensions match the request (dataset_type + instrument_id + source + interval fields etc.) and whose status='fresh' and as_of is within ttl_seconds; otherwise fetch upstream, store a new cache row, and set tool_calls.cache_hit=false.
- get_realtime_data with symbol=null must return a market-wide snapshot (implementation-defined) and must store instrument_id null in tool_calls and market_data_cache when cached.
- tool_calls.status transitions must follow: received -> running -> (succeeded|failed) with no other transitions; updated_at must be set on each transition and error_message must be non-null iff status='failed'.
- api_keys.status='revoked' keys must be rejected; successful calls should update api_keys.last_used_at.
- Upstream `source` must be recorded exactly as provided/used and must be one of the tool-supported enums (eastmoney, eastmoney_direct, sina, xueqiu); get_cash_flow defaults to source='sina' when omitted; get_realtime_data defaults to source='xueqiu' when omitted; get_hist_data defaults to source='eastmoney' when omitted.