# Crypto Indicators MCP Server — local MCP environment

This backend supports an MCP server that computes technical indicators and simple trading signals (BUY/HOLD/SELL) for crypto trading pairs using OHLCV candlestick data sourced from Binance. The main workflows are: resolving/normalizing a requested symbol and timeframe, ensuring OHLCV candles are available (from cache or by fetching), executing an indicator/strategy computation job, and returning the latest computed series/value while recording usage and job outcomes.

Repository: https://github.com/kukapay/crypto-indicators-mcp
Homepage: https://smithery.ai/server/@kukapay/crypto-indicators-mcp

## Datastore

- `trading_pairs.json` — Canonical set of supported trading pairs/symbols (primarily Binance symbols) and their metadata used for OHLCV retrieval and computation requests. (18 rows; fields: ['id', 'exchange', 'symbol', 'base_asset', 'quote_asset', 'price_precision', 'quantity_precision', 'min_notional', 'status', 'first_seen_at', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'delisted']
  - constraint: unique(exchange, symbol)
  - constraint: symbol != ''
  - constraint: base_asset != ''
  - constraint: quote_asset != ''
- `ohlcv_candles.json` — Time-series candlestick OHLCV data cached from Binance for each trading pair and interval; used as input to indicator computations. (17 rows; fields: ['id', 'pair_id', 'interval', 'open_time', 'close_time', 'open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trade_count', 'source', 'ingest_status', 'created_at', 'updated_at'])
  - lifecycle `ingest_status`: ['confirmed', 'provisional', 'corrected']
  - constraint: unique(pair_id, interval, open_time)
  - constraint: open_time < close_time
  - constraint: open > 0 and high > 0 and low > 0 and close > 0
  - constraint: high >= max(open, close, low)
- `indicator_definitions.json` — Registry of supported indicator and strategy computations exposed as MCP tools; used for validation, routing to the correct computation function, and caching policy. (18 rows; fields: ['id', 'tool_name', 'category', 'library', 'output_kind', 'min_lookback_candles', 'default_interval', 'default_limit', 'cache_ttl_seconds', 'is_enabled', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: unique(tool_name)
  - constraint: min_lookback_candles >= 1
  - constraint: default_limit >= min_lookback_candles
  - constraint: cache_ttl_seconds >= 0
- `computation_jobs.json` — Execution records for indicator/strategy computations triggered by MCP tool calls, including inputs, cache keys, timing, and errors. (19 rows; fields: ['id', 'indicator_id', 'pair_id', 'interval', 'candle_limit', 'input_start_time', 'input_end_time', 'request_fingerprint', 'cache_hit', 'status', 'queued_at', 'started_at', 'finished_at', 'error_code', 'error_message', 'binance_request_count', 'compute_time_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: candle_limit >= 1
  - constraint: binance_request_count >= 0
  - constraint: compute_time_ms is null or compute_time_ms >= 0
  - constraint: unique(request_fingerprint) where status in ('succeeded') and finished_at is not null
- `computation_results.json` — Persisted outputs for computation jobs (indicator series/multi-series or strategy signals), enabling caching and later inspection. (19 rows; fields: ['id', 'job_id', 'result_kind', 'as_of_time', 'value', 'signal', 'series', 'multi_series', 'metadata', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `result_kind`: ['series', 'multi_series', 'signal']
  - constraint: unique(job_id)
  - constraint: job_id references computation_jobs(id) on delete cascade
  - constraint: as_of_time is not null
  - constraint: expires_at is null or expires_at >= created_at

## Business rules enforced by the tools

- Each MCP tool name maps 1:1 to indicator_definitions.tool_name; executing any tool requires indicator_definitions.is_enabled = true and status in ('active','deprecated').
- All calculations must use OHLCV candles scoped by (pair_id, interval) and ordered by open_time; the service must ensure at least indicator_definitions.min_lookback_candles candles are available or fail the job with error_code = 'INSUFFICIENT_DATA'.
- For any strategy tool, computation_results.result_kind must be 'signal' and computation_results.signal must be one of -1, 0, 1 (SELL/HOLD/BUY).
- OHLCV ingestion must enforce uniqueness on (pair_id, interval, open_time) and must reject candles where low > high or where open/close fall outside [low, high].
- A computation_job may transition only according to the declared lifecycle; on terminal states (succeeded/failed/cancelled), finished_at must be set and updated_at must be >= finished_at.
- Caching/deduplication: if a succeeded computation_job exists with the same request_fingerprint and its computation_result.expires_at is null or in the future, subsequent identical requests must set cache_hit = true and return that stored computation_result without recomputation.
- Trading pairs with status != 'active' must not be used for new computation_jobs; attempts must fail with error_code = 'PAIR_DISABLED'.