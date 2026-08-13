# Alpha Vantage Stock Server — local MCP environment

This backend powers a lightweight stock-data service backed by Alpha Vantage, storing ingested time-series market data, computed snapshots, and user-defined alert rules. The primary workflows are: periodically fetching daily OHLCV data, serving latest/overview stock data reads, and evaluating alert conditions to produce active alerts returned by the API.

Repository: https://github.com/qubaomingg/stock-analysis-mcp
Homepage: https://smithery.ai/server/@qubaomingg/stock-analysis-mcp

## Datastore

- `symbols.json` — Master list of supported equities/tickers and their basic metadata used for data ingestion and client reads. (18 rows; fields: ['id', 'ticker', 'exchange', 'name', 'currency', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'delisted']
  - constraint: unique(ticker, exchange)
  - constraint: ticker <> ''
  - constraint: status in ('active','disabled','delisted')
- `daily_prices.json` — Daily OHLCV time-series bars per symbol, sourced from Alpha Vantage TIME_SERIES_DAILY (adjusted or unadjusted depending on implementation). (19 rows; fields: ['id', 'symbol_id', 'trading_date', 'open', 'high', 'low', 'close', 'volume', 'source', 'ingestion_job_id', 'created_at', 'updated_at'])
  - lifecycle `source`: ['alpha_vantage']
  - constraint: unique(symbol_id, trading_date)
  - constraint: open >= 0 and high >= 0 and low >= 0 and close >= 0
  - constraint: high >= low
  - constraint: high >= open and high >= close
- `stock_snapshots.json` — Latest computed per-symbol snapshot used to serve fast "get-stock-data" responses (e.g., last close, day change, and last refresh time). (18 rows; fields: ['id', 'symbol_id', 'as_of_date', 'last_close', 'prev_close', 'day_change', 'day_change_pct', 'status', 'refreshed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'unavailable']
  - constraint: unique(symbol_id)
  - constraint: last_close >= 0
  - constraint: prev_close is null or prev_close >= 0
  - constraint: day_change_pct is null or (day_change_pct >= -1 and day_change_pct <= 1000)
- `alert_rules.json` — User/system-defined alert rules for symbols. Rules are evaluated on new daily bars and/or snapshots and can produce active alerts. (18 rows; fields: ['id', 'symbol_id', 'rule_type', 'threshold_number', 'threshold_integer', 'is_recurring', 'cooldown_minutes', 'last_triggered_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'paused', 'deleted']
  - constraint: foreign key (symbol_id) references symbols(id) on delete cascade
  - constraint: cooldown_minutes >= 0 and cooldown_minutes <= 525600
  - constraint: ((rule_type in ('price_above','price_below','pct_change_above','pct_change_below') and threshold_number is not null and threshold_integer is null) or (rule_type = 'volume_above' and threshold_integer is not null and threshold_number is null))
  - constraint: threshold_number is null or threshold_number >= 0
- `alerts.json` — Materialized alert events created when an alert_rule condition is met. Returned by get-stock-alerts. (18 rows; fields: ['id', 'alert_rule_id', 'symbol_id', 'triggered_on_date', 'observed_value_number', 'observed_value_integer', 'message', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'acknowledged', 'expired']
  - constraint: foreign key (alert_rule_id) references alert_rules(id) on delete cascade
  - constraint: foreign key (symbol_id) references symbols(id) on delete cascade
  - constraint: observed_value_number is null or observed_value_number >= 0
  - constraint: observed_value_integer is null or observed_value_integer >= 0
- `ingestion_jobs.json` — Tracks fetch/refresh runs against Alpha Vantage (scheduled or on-demand) to populate daily_prices and update snapshots. Used for auditing, rate-limit safety, and troubleshooting. (19 rows; fields: ['id', 'job_type', 'symbol_id', 'requested_at', 'started_at', 'finished_at', 'status', 'alpha_vantage_endpoint', 'http_status_code', 'error_code', 'error_message', 'rows_upserted', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: rows_upserted >= 0
  - constraint: http_status_code is null or (http_status_code >= 100 and http_status_code <= 599)
  - constraint: foreign key (symbol_id) references symbols(id) on delete set null
  - constraint: finished_at is null or started_at is not null

## Business rules enforced by the tools

- Tool get-daily-stock-data reads from daily_prices joined to symbols; if no daily_prices exist for an active symbol, the service must enqueue an ingestion_jobs row (job_type='refresh_symbol_daily') or return an empty dataset depending on deployment configuration.
- Tool get-stock-data reads from stock_snapshots joined to symbols; snapshots must be recomputed from the most recent daily_prices per symbol and marked status='stale' if refreshed_at is older than a configured TTL (e.g., 24h) or if symbol.status != 'active'.
- Tool get-stock-alerts returns alerts where status in ('active') by default; acknowledging an alert must transition alerts.status from 'active' to 'acknowledged' only.
- Alert evaluation must only consider alert_rules with status='active' and symbols.status='active'.
- For a non-recurring alert rule (is_recurring=false), when it triggers the rule must transition to status='paused' (or be left active but prevented by last_triggered_at); recurring rules must respect cooldown_minutes and must not produce multiple alerts within the cooldown window.
- daily_prices upserts must preserve uniqueness(symbol_id, trading_date); updates are allowed only if the source is alpha_vantage and the ingestion job is the latest succeeded job for that symbol/day.
- ingestion_jobs.status transitions must follow the declared transition graph; once a job is in a terminal state (succeeded/failed/cancelled) it must not change.
- Deleting a symbol (rare admin operation) must cascade-delete its daily_prices, stock_snapshots, alert_rules, and alerts via FK rules, ensuring no orphaned rows.