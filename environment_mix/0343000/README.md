# Yahoo Finance Data Server — local MCP environment

This backend stores a local cache of Yahoo Finance market data keyed by symbol, plus provider fetch jobs and request audit logs. Read tools serve from the cache when fresh; on cache miss or staleness they enqueue a fetch job, persist the normalized results (prices, fundamentals, news, recommendations, events), and return the latest available snapshot.

Repository: https://github.com/marckwei/no-use-tools
Homepage: https://smithery.ai/server/@marckwei/no-use-tools

## Datastore

- `symbols.json` — Master reference for Yahoo Finance symbols/tickers and basic metadata used to normalize all downstream data (prices, fundamentals, news, etc.). (18 rows; fields: ['id', 'symbol', 'exchange', 'short_name', 'long_name', 'quote_type', 'currency', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'blocked']
  - constraint: unique(symbol)
  - constraint: symbol length between 1 and 20
  - constraint: status in ('active','inactive','blocked')
- `market_data_points.json` — Time-series market data and corporate actions for a symbol: OHLCV bars, current/spot price snapshots, and dividend events. (17 rows; fields: ['id', 'symbol_id', 'data_type', 'as_of', 'trading_date', 'interval', 'open', 'high', 'low', 'close', 'adj_close', 'volume', 'spot_price', 'dividend_amount', 'dividend_currency', 'source_job_id', 'created_at', 'updated_at'])
  - lifecycle `data_type`: ['price_bar', 'spot_price', 'dividend']
  - constraint: fk(symbol_id) references symbols(id) on delete cascade
  - constraint: fk(source_job_id) references fetch_jobs(id) on delete set null
  - constraint: unique(symbol_id, data_type, as_of, interval)
  - constraint: when data_type='price_bar' then interval is not null and trading_date is not null and open/high/low/close are not null
- `fundamental_statements.json` — Normalized financial statements for a symbol (income statement and cashflow) at a specified frequency. (19 rows; fields: ['id', 'symbol_id', 'statement_type', 'freq', 'period_end_date', 'currency', 'data', 'source_job_id', 'created_at', 'updated_at'])
  - lifecycle `statement_type`: ['income_statement', 'cashflow']
  - constraint: fk(symbol_id) references symbols(id) on delete cascade
  - constraint: fk(source_job_id) references fetch_jobs(id) on delete set null
  - constraint: unique(symbol_id, statement_type, freq, period_end_date)
  - constraint: period_end_date matches ^\d{4}-\d{2}-\d{2}$
- `content_items.json` — Content returned by Yahoo Finance tied to a symbol: analyst recommendations, news articles, and earnings dates/events. (19 rows; fields: ['id', 'symbol_id', 'content_type', 'provider_item_id', 'published_at', 'effective_date', 'title', 'url', 'summary', 'payload', 'status', 'source_job_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded', 'deleted']
  - constraint: fk(symbol_id) references symbols(id) on delete cascade
  - constraint: fk(source_job_id) references fetch_jobs(id) on delete set null
  - constraint: unique(symbol_id, content_type, provider_item_id) where provider_item_id is not null
  - constraint: effective_date matches ^\d{4}-\d{2}-\d{2}$ when not null
- `fetch_jobs.json` — Tracks provider fetches to Yahoo Finance triggered by read APIs (cache warming), including parameters like period/interval/freq and outcome/errors. (18 rows; fields: ['id', 'symbol_id', 'tool_name', 'request_params', 'cache_key', 'status', 'priority', 'started_at', 'finished_at', 'error_message', 'result_summary', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(symbol_id) references symbols(id) on delete set null
  - constraint: priority between 0 and 100
  - constraint: unique(cache_key) where cache_key is not null and status in ('queued','running')
  - constraint: tool_name in (listed enum)
- `api_request_logs.json` — Audit log of tool invocations for observability, debugging, and quota/rate limiting; includes cmd_run invocations. (18 rows; fields: ['id', 'tool_name', 'symbol_id', 'fetch_job_id', 'request_params', 'response_status', 'duration_ms', 'cache_hit', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `response_status`: [100, 101, 102, 200, 201, 202, 204, 301, 302, 304, 400, 401, 403, 404, 409, 422, 429, 500, 502, 503]
  - constraint: fk(symbol_id) references symbols(id) on delete set null
  - constraint: fk(fetch_job_id) references fetch_jobs(id) on delete set null
  - constraint: duration_ms >= 0
  - constraint: response_status between 100 and 599

## Business rules enforced by the tools

- For any tool call with parameter symbol, the backend must upsert symbols(symbol) and use symbols.id as the canonical foreign key in all downstream writes.
- get_current_stock_price(symbol) reads the most recent market_data_points row where data_type='spot_price' for the symbol; if older than 30 seconds, enqueue a fetch_jobs row (tool_name='get_current_stock_price') unless an existing queued/running job with the same cache_key exists.
- get_stock_price_by_date(symbol, date) must return a price_bar where trading_date = date and interval='1d'; if missing, it must enqueue a fetch job with request_params including date and a cache_key derived from (symbol, 'by_date', date).
- get_stock_price_date_range(symbol, start_date, end_date) must validate start_date <= end_date and serve price_bar rows where trading_date is within the range and interval='1d'; if coverage is incomplete, enqueue a fetch job with a cache_key derived from (symbol, 'range', start_date, end_date).
- get_historical_stock_prices(symbol, period, interval) must validate period and interval against the allowed enums; it serves price_bar rows for the computed date range; if the latest datapoint is stale beyond the expected interval, enqueue a fetch job keyed by (symbol, period, interval).
- get_dividends(symbol) returns market_data_points rows where data_type='dividend' ordered by as_of desc; dividends are deduplicated by unique(symbol_id, data_type, as_of, interval) with interval null for dividends.
- get_income_statement(symbol, freq) and get_cashflow(symbol, freq) must validate freq in ('yearly','quarterly','trainling'); they return fundamental_statements filtered by statement_type and freq, ordered by period_end_date desc.
- get_news(symbol) returns content_items where content_type='news' and status='active' ordered by published_at desc; news items are deduplicated when provider_item_id is present via unique(symbol_id, content_type, provider_item_id).
- get_recommendations(symbol) returns content_items where content_type='recommendation' and status='active' ordered by published_at desc (or created_at when missing).
- get_earning_dates(symbol, limit) must treat limit as an integer if provided; it returns at most limit content_items where content_type='earning_date' and status='active', ordered by effective_date desc (recent) and then upcoming; limit must be within 1..200.
- cmd_run(cmd) must create an api_request_logs row with tool_name='cmd_run' and request_params.cmd set; it must never write into market data collections unless the command explicitly triggers an internal ingestion pipeline (represented as a fetch_jobs row with tool_name='cmd_run').
- fetch_jobs status transitions must follow the declared lifecycle; in particular, a job cannot move from succeeded to any other status, and finished_at must be set when status in ('succeeded','failed','cancelled').