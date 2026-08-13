# Yahoo Finance Data and Visualization Server — local MCP environment

This backend powers an API facade over Yahoo Finance, caching market data (prices, corporate actions, fundamentals, earnings, and news) by ticker symbol and tracking visualization/report generation jobs that return base64-encoded PNGs. Core workflows are (1) read-through caching of Yahoo Finance responses keyed by symbol/date/range/period/interval and (2) asynchronous generation and storage of dashboard/report images with status and retention controls.

Repository: https://github.com/leoncuhk/mcp-yahoo-finance
Homepage: https://smithery.ai/server/@leoncuhk/mcp-yahoo-finance

## Datastore

- `instruments.json` — Canonical list of Yahoo Finance instruments (tickers/indices) known to the system. Used to normalize symbol handling across all endpoints and to support caching and reporting. (19 rows; fields: ['id', 'symbol', 'instrument_type', 'exchange', 'currency', 'display_name', 'timezone', 'status', 'first_seen_at', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'delisted', 'blocked']
  - constraint: unique(symbol)
  - constraint: symbol length between 1 and 24
  - constraint: symbol matches ^[A-Za-z0-9.^=\-]+$
  - constraint: created_at <= updated_at
- `price_bars.json` — Time series OHLCV bars used to answer current price, by-date price, date-range, and historical queries at various intervals. Acts as the main cache for chart/history endpoints. (18 rows; fields: ['id', 'instrument_id', 'interval', 'bar_start_at', 'trading_date', 'open', 'high', 'low', 'close', 'adj_close', 'volume', 'source', 'quality', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `quality`: ['estimated', 'partial', 'final']
  - constraint: unique(instrument_id, interval, bar_start_at)
  - constraint: open >= 0 or open is null
  - constraint: high >= 0 or high is null
  - constraint: low >= 0 or low is null
- `corporate_actions.json` — Cached corporate actions events used to serve dividends for a symbol and support adjusted price interpretation. (18 rows; fields: ['id', 'instrument_id', 'action_type', 'ex_date', 'pay_date', 'amount', 'currency', 'split_numerator', 'split_denominator', 'source', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `action_type`: ['dividend', 'split']
  - constraint: unique(instrument_id, action_type, ex_date, coalesce(amount, -1), coalesce(split_numerator, -1), coalesce(split_denominator, -1))
  - constraint: amount is null or amount >= 0
  - constraint: split_numerator is null or split_numerator > 0
  - constraint: split_denominator is null or split_denominator > 0
- `fundamentals.json` — Cached financial statement snapshots used to serve income statement and cashflow endpoints at yearly/quarterly frequency. (10 rows; fields: ['id', 'instrument_id', 'statement_type', 'frequency', 'period_end_date', 'currency', 'data', 'source', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `frequency`: ['yearly', 'quarterly', 'trainling']
  - constraint: unique(instrument_id, statement_type, frequency, period_end_date)
  - constraint: data must be a non-empty object
  - constraint: created_at <= updated_at
- `events_and_reports.json` — Stores earnings dates, news items, and generated visualization artifacts. Combines multiple tool outputs with a typed schema and status lifecycle for generation jobs. (18 rows; fields: ['id', 'record_type', 'instrument_id', 'scheduled_for_date', 'earnings_time_hint', 'news_published_at', 'news_title', 'news_url', 'news_source', 'render_kind', 'render_params', 'status', 'result_mime_type', 'result_base64', 'result_size_bytes', 'error_message', 'source', 'fetched_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'ready', 'failed', 'expired']
  - constraint: if record_type in ('earning_date','news_item') then status = 'ready'
  - constraint: if record_type = 'earning_date' then instrument_id is not null and scheduled_for_date is not null
  - constraint: if record_type = 'news_item' then instrument_id is not null and news_title is not null and news_url is not null
  - constraint: if record_type = 'render_job' then render_kind is not null and render_params is not null

## Business rules enforced by the tools

- When any tool is called with a symbol, the service must upsert instruments(symbol) and set last_seen_at=now(); if instruments.status='blocked' the request must be rejected.
- get_current_stock_price(symbol) must return the latest available price_bars row for that instrument at interval='1d' (or the smallest available interval), preferring quality='final' and highest bar_start_at; if cache is stale (fetched_at older than 60s for intraday-equivalent, or older than 15m for daily), refresh from upstream before responding.
- get_stock_price_by_date(symbol,date) must return the price_bars row where trading_date=date at interval='1d' (or closest trading session rule configured); if missing, fetch the minimal range covering date and upsert bars.
- get_stock_price_date_range(symbol,start_date,end_date) must validate start_date <= end_date and return ordered price_bars rows with trading_date between bounds at interval='1d' unless upstream interval is required; if the requested range exceeds available cache coverage, fetch missing segments and upsert.
- get_historical_stock_prices(symbol,period,interval) must enforce period in {1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max} and interval in {1d,5d,1wk,1mo,3mo}; it must map period+interval to an upstream fetch window, then serve from price_bars with the matching interval and bar_start_at within that window.
- get_dividends(symbol) must return corporate_actions rows where action_type='dividend' for the instrument, ordered by ex_date desc; if none exist or fetched_at is older than 7d, refresh from upstream.
- get_income_statement(symbol,freq) and get_cashflow(symbol,freq) must enforce freq in {yearly,quarterly,trainling} and return fundamentals rows filtered by (statement_type,frequency) ordered by period_end_date desc; if stale (fetched_at older than 7d) refresh.
- get_earning_dates(symbol,limit) must enforce 1 <= limit <= 200, returning up to limit events_and_reports rows with record_type='earning_date' ordered by scheduled_for_date desc/asc per API contract; if stale (fetched_at older than 24h) refresh.
- get_news(symbol) must return events_and_reports rows with record_type='news_item' ordered by news_published_at desc; duplicates must be prevented by unique(instrument_id,record_type,news_url); refresh if stale (fetched_at older than 1h).
- generate_market_dashboard(indices) must parse indices as a comma-separated list (1..20 symbols). For each symbol, ensure instrument exists and instrument_type is 'index' or 'unknown'; then create (or reuse) a render_job row with render_kind='market_dashboard' and render_params.indices=[...]. It must transition status queued->running->ready/failed and store base64 PNG in result_base64 (<=10MB).
- generate_portfolio_report(symbols) must parse symbols as a comma-separated list (1..50 symbols), ensure instruments exist and are not blocked, then create/reuse a render_job with render_kind='portfolio_report' and render_params.symbols=[...].
- generate_stock_technical_analysis(symbol) must ensure instrument exists and is not blocked, then create/reuse a render_job with render_kind='stock_technical_analysis' and instrument_id set; render_params.symbol must equal instruments.symbol.
- Render job deduplication: if an existing render_job with the same render_kind and render_params (and instrument_id where applicable) is in status='ready' and not expired (expires_at > now()), the tool should return that cached result instead of regenerating.
- Retention: render_job rows should set expires_at (e.g. now()+24h) and may be moved to status='expired' by a sweeper; expired jobs must not return result_base64.
- FK integrity must be enforced: instrument_id in dependent collections must reference instruments.id; deletes of instruments must be restricted when dependent rows exist.