# Groww MCP Server — local MCP environment

This backend powers a trading/market-data MCP server for Groww: it ingests and indexes Groww instruments, proxies/records order and portfolio workflows, and caches market/historical data used by technical analysis tools. Core workflows include instrument CSV ingestion, searching/reading instrument metadata, placing/modifying/canceling orders with lifecycle tracking, and retrieving/caching quotes and candles to compute indicators and pattern analysis.

Repository: https://github.com/arkapravasinha/groww-mcp-server
Homepage: https://smithery.ai/server/@arkapravasinha/groww-mcp-server

## Datastore

- `instrument_import_jobs.json` — Tracks downloads/ingestion of the Groww instruments CSV and indexing outcomes used by search and instrument detail tools. (17 rows; fields: ['id', 'source', 'download_url', 'etag', 'content_sha256', 'byte_size', 'started_at', 'finished_at', 'imported_instruments_count', 'error_message', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'downloading', 'parsing', 'indexing', 'completed', 'failed', 'cancelled']
  - constraint: unique(content_sha256) where content_sha256 is not null
  - constraint: byte_size is null or byte_size >= 0
  - constraint: imported_instruments_count is null or imported_instruments_count >= 0
- `instruments.json` — Master catalog of tradable instruments loaded from Groww instruments CSV; supports search, details, quoting, OHLC/LTP, and historical queries. (19 rows; fields: ['id', 'import_job_id', 'exchange', 'segment', 'instrument_type', 'trading_symbol', 'groww_symbol', 'isin', 'name', 'underlying_symbol', 'expiry_date', 'strike_price', 'option_type', 'lot_size', 'tick_size', 'status', 'search_keywords', 'raw_payload', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'delisted']
  - constraint: unique(exchange, trading_symbol)
  - constraint: unique(groww_symbol) where groww_symbol is not null
  - constraint: lot_size is null or lot_size > 0
  - constraint: tick_size is null or tick_size > 0
- `orders.json` — Order lifecycle records created/modified/cancelled via Groww order endpoints; supports listing, status checks (by order_id or user reference), and order details/trades linkage. (21 rows; fields: ['id', 'groww_order_id', 'user_reference_id', 'instrument_id', 'trading_symbol', 'exchange', 'product', 'order_type', 'side', 'quantity', 'price', 'trigger_price', 'disclosed_quantity', 'validity', 'client_timestamp', 'submitted_to_broker_at', 'last_status_at', 'status', 'broker_status', 'rejection_reason', 'raw_request', 'raw_response', 'created_at', 'updated_at'])
  - lifecycle `status`: ['created', 'pending', 'open', 'partially_filled', 'filled', 'cancelled', 'rejected', 'expired', 'failed']
  - constraint: unique(groww_order_id) where groww_order_id is not null
  - constraint: unique(user_reference_id) where user_reference_id is not null
  - constraint: quantity > 0
  - constraint: disclosed_quantity is null or (disclosed_quantity > 0 and disclosed_quantity <= quantity)
- `trades.json` — Trade/execution fills linked to orders; supports get_order_trades and enriches order details. (18 rows; fields: ['id', 'order_id', 'groww_trade_id', 'exchange_trade_id', 'fill_quantity', 'fill_price', 'fill_value', 'trade_time', 'status', 'raw_payload', 'created_at', 'updated_at'])
  - lifecycle `status`: ['reported', 'corrected', 'cancelled']
  - constraint: unique(order_id, groww_trade_id) where groww_trade_id is not null
  - constraint: fill_quantity > 0
  - constraint: fill_price > 0
  - constraint: fill_value is null or fill_value >= 0
- `portfolio_snapshots.json` — Cached snapshots of holdings, positions, and margin for the authenticated user; supports get_holdings, get_positions, get_position_by_symbol, and get_user_margin. (18 rows; fields: ['id', 'as_of', 'snapshot_type', 'status', 'ttl_seconds', 'data', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'failed']
  - constraint: ttl_seconds >= 0
  - constraint: unique(snapshot_type, as_of)
- `market_data_cache.json` — Cache for live quotes/LTP/OHLC and historical candle series used by market data tools and technical analysis calculations. (19 rows; fields: ['id', 'instrument_id', 'data_type', 'timeframe', 'from_ts', 'to_ts', 'max_points', 'derived_from_cache_id', 'algorithm', 'parameters', 'as_of', 'ttl_seconds', 'status', 'payload', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'failed']
  - constraint: ttl_seconds >= 0
  - constraint: max_points is null or (max_points > 0 and max_points <= 50000)
  - constraint: unique(instrument_id, data_type, timeframe, from_ts, to_ts, algorithm, as_of)
  - constraint: data_type in ('historical_candles','indicator_result') implies timeframe is not null

## Business rules enforced by the tools

- download_instruments_csv must create an instrument_import_jobs row and transition status queued->downloading->parsing->indexing->completed (or ->failed); on completion it must upsert instruments using unique(exchange, trading_symbol).
- search_instruments must query instruments by case-insensitive partial match across name, trading_symbol, groww_symbol, isin and search_keywords; only instruments.status='active' are returned unless explicitly requested by internal callers.
- get_instrument_details must resolve by trading_symbol (and optionally exchange if ambiguous) using instruments.unique(exchange, trading_symbol); if multiple matches exist due to UNKNOWN exchange, the tool must return an error requiring disambiguation.
- place_order must insert an orders row with status='created' then update groww_order_id/raw_response and status to broker-returned state; quantity must be > 0 and instrument_id must exist.
- modify_order is only allowed when orders.status in ('pending','open','partially_filled'); modifications must update raw_request/raw_response and updated_at, and must not reduce quantity below total filled quantity derived from trades for that order.
- cancel_order is only allowed when orders.status in ('pending','open','partially_filled'); cancelling must transition to 'cancelled' unless broker rejects, in which case transition to 'rejected' or 'failed' with rejection_reason set.
- get_order_status must locate by unique(groww_order_id) and return latest orders.status plus broker_status/raw_response; get_order_status_by_reference must locate by unique(user_reference_id).
- get_order_list for the day must filter orders by created_at in [market_day_start, market_day_end] in server timezone, sorted by created_at desc; pagination is server-defined.
- get_order_trades must return trades where trades.order_id matches the resolved order; fills must satisfy fill_quantity>0 and fill_price>0.
- get_holdings/get_positions/get_user_margin must return the most recent portfolio_snapshots row for the relevant snapshot_type with status='fresh'; if none is fresh, fetch upstream and write a new snapshot with status='fresh' or 'failed'.
- get_position_by_symbol must match requested trading_symbol to instruments then filter the latest positions snapshot payload by that symbol; if instrument is not found, return an error.
- get_live_quote/get_ltp/get_ohlc must use market_data_cache with data_type live_quote/ltp/ohlc; if a fresh cache entry exists within ttl_seconds it must be returned, otherwise fetch upstream and store a new cache entry.
- get_ltp and get_ohlc must enforce a maximum of 50 instruments per request; the implementation must refuse larger batches.
- get_historical_data must enforce timeframe/date-range constraints: 1min<=3 days, 5min<=15 days, 10min<=30 days, 1hr<=150 days, 4hr<=365 days, daily<=1080 days, weekly unlimited; requests outside bounds must be rejected before fetching/storing.
- Technical indicator tools (moving averages, rsi, bollinger, macd, stochastic, williams_r, adx, fibonacci, support_resistance, volatility_metrics, candlestick_patterns) must read from or create a market_data_cache entry with data_type='indicator_result' and derived_from_cache_id pointing to the historical_candles cache used as input; parameters must be stored in market_data_cache.parameters for reproducibility.
- get_current_date returns server time and does not require persistence; however, if auditing is desired, calls may be logged out-of-band and must not mutate these core collections.