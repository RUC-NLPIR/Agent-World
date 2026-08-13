# A-Share Market Data Server — local MCP environment

This backend stores normalized A-share market reference data (securities, trading calendar, index constituents, industry classification) plus time-series datasets (OHLCV K-line, adjust factors, corporate actions/dividends, financial statements, and macro/interest-rate series). Read tools query these datasets by code and date ranges; an internal ingestion lifecycle tracks what vendor snapshots were loaded and validated so responses are reproducible and cacheable.

Repository: https://github.com/24mlight/a-share-mcp-is-just-i-need
Homepage: https://smithery.ai/server/@24mlight/a-share-mcp-is-just-i-need

## Datastore

- `securities.json` — Master list of A-share equities and indices in Baostock code format, including basic profile fields used by basic-info and list-all-stock endpoints. (18 rows; fields: ['id', 'bs_code', 'exchange', 'symbol', 'name', 'security_type', 'industry_name', 'industry_code', 'listing_date', 'delisting_date', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'delisted']
  - constraint: unique(bs_code)
  - constraint: exchange in ('sh','sz','bj','idx')
  - constraint: security_type in ('equity','index')
  - constraint: if delisting_date is not null then status = 'delisted'
- `market_calendar.json` — Trading calendar and per-security trading status snapshots for specific dates. Supports get_trade_dates, get_latest_trading_date, and get_all_stock(date) trading/suspension status. (18 rows; fields: ['id', 'trading_date', 'is_trade_day', 'notes', 'created_at', 'updated_at'])
  - lifecycle `is_trade_day`: ['false', 'true']
  - constraint: unique(trading_date)
- `reference_classifications.json` — Slow-changing reference datasets: stock industry classifications over time and index constituents for SZ50/HS300/ZZ500. Supports get_stock_industry and get_*_stocks(date). (18 rows; fields: ['id', 'ref_type', 'as_of_date', 'security_id', 'industry_code', 'industry_name', 'index_code', 'weight', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded']
  - constraint: ref_type in ('industry','index_constituent')
  - constraint: if ref_type='industry' then index_code is null
  - constraint: if ref_type='index_constituent' then index_code in ('sz50','hs300','zz500') and industry_code is null and industry_name is null
  - constraint: unique(ref_type, as_of_date, security_id, index_code)
- `security_time_series.json` — All per-security time series required by tools: K-line OHLCV, adjust factors, dividends/corporate actions, and performance/forecast reports with publication dates. (18 rows; fields: ['id', 'series_type', 'security_id', 'trade_date', 'frequency', 'adjust_flag', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turn', 'pct_chg', 'adjust_factor', 'dividend_year', 'dividend_year_type', 'dividend_payload', 'pub_date', 'report_payload', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'corrected', 'retracted']
  - constraint: series_type in ('kline','adjust_factor','dividend','performance_express','performance_forecast')
  - constraint: if series_type in ('kline','adjust_factor') then trade_date is not null
  - constraint: if series_type='kline' then frequency is not null and adjust_flag is not null
  - constraint: if series_type='kline' then open is not null and high is not null and low is not null and close is not null and volume is not null
- `fundamentals_and_macro.json` — Quarterly financial statement-derived indicators (profit/operation/growth/balance/cashflow/dupont) per security, plus macro/interest-rate time series (deposit/loan/rrr/money-supply/shibor). Designed to serve range queries and stock analysis assembly. (18 rows; fields: ['id', 'dataset_type', 'security_id', 'year', 'quarter', 'period_month', 'as_of_date', 'year_type', 'payload', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'corrected', 'retracted']
  - constraint: dataset_type in ('profit','operation','growth','balance','cash_flow','dupont','deposit_rate','loan_rate','required_reserve_ratio','money_supply_month','money_supply_year','shibor')
  - constraint: if dataset_type in ('profit','operation','growth','balance','cash_flow','dupont') then security_id is not null and year is not null and quarter is not null
  - constraint: if dataset_type in ('profit','operation','growth','balance','cash_flow','dupont') then quarter >= 1 and quarter <= 4
  - constraint: if dataset_type='money_supply_month' then period_month is not null
- `ingestion_jobs.json` — Internal ingestion/caching ledger for vendor pulls (Baostock) enabling reproducibility, freshness checks used implicitly by 'latest trading date' and analysis timeframe logic, and operational monitoring. (19 rows; fields: ['id', 'job_type', 'vendor', 'requested_params', 'dataset_fingerprint', 'row_count', 'started_at', 'finished_at', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: row_count is null or row_count >= 0
  - constraint: finished_at is null or finished_at >= started_at
  - constraint: unique(job_type, vendor, started_at)

## Business rules enforced by the tools

- All tools that accept a 'code' must resolve it to securities.bs_code; if the code does not exist, the request must return a not-found error and MUST NOT create a new security implicitly.
- For get_historical_k_data(code,start_date,end_date,frequency,adjust_flag,fields): query security_time_series where series_type='kline', security_id matches, trade_date between start_date and end_date inclusive, frequency matches (default 'd'), adjust_flag matches (default '3'), and status='active'. If fields is null/empty return all kline columns; otherwise project only requested columns and always include trade_date.
- For get_adjust_factor_data(code,start_date,end_date): query security_time_series where series_type='adjust_factor' and trade_date within range and status='active'.
- For get_dividend_data(code,year,year_type): query security_time_series where series_type='dividend', dividend_year=year, dividend_year_type=year_type (default 'report'), status='active'.
- For quarterly fundamentals tools (get_profit_data/get_operation_data/get_growth_data/get_balance_data/get_cash_flow_data/get_dupont_data): query fundamentals_and_macro by dataset_type, security_id, year, quarter; quarter must be in [1,4] or the request is rejected.
- For get_performance_express_report/get_forecast_report: query security_time_series by series_type ('performance_express'/'performance_forecast'), security_id and pub_date between start_date and end_date inclusive, status='active'.
- For get_stock_industry(code?,date?): if date is null select max(as_of_date) where ref_type='industry'; if code is provided filter by security_id. Return only rows with status='active'.
- For get_sz50_stocks/get_hs300_stocks/get_zz500_stocks(date?): map tool to index_code ('sz50','hs300','zz500'); if date is null select latest as_of_date for that index_code; return reference_classifications rows with ref_type='index_constituent' and status='active'.
- For get_trade_dates(start_date?,end_date?): default start_date='2015-01-01' and end_date=today; query market_calendar between range inclusive; missing dates in calendar are not allowed in responses (ingestion must ensure complete coverage).
- For get_latest_trading_date: return max(trading_date) from market_calendar where trading_date <= today and is_trade_day=true; if today exists and is_trade_day=true return today.
- For deposit/loan/shibor/rrequired_reserve_ratio tools: query fundamentals_and_macro by dataset_type and as_of_date between start_date and end_date inclusive; for required_reserve_ratio also filter by year_type (default '0').
- For money supply month/year tools: filter fundamentals_and_macro by dataset_type and period_month/year between start_date and end_date (lexicographic comparisons are valid only if formats are strictly 'YYYY-MM' and 'YYYY'). Requests must validate formats before querying.
- get_market_analysis_timeframe(period): period must be one of ('recent','quarter','half_year','year'); returned range must end at get_latest_trading_date and begin at an offset that approximates 1-2 months/1 quarter/6 months/1 year; the chosen begin date must be snapped to the nearest earlier trade day using market_calendar.
- get_stock_analysis(code,analysis_type): analysis_type must be one of ('fundamental','technical','comprehensive'); the report must be derived only from stored datasets above (kline, adjust factors, quarterly fundamentals, industry classification, index constituents, and calendar) and must not claim availability of fields absent from payloads.
- All FK references must enforce integrity: reference_classifications.security_id and time-series security_id must exist in securities; deleting a security is disallowed if referenced by any row (restrict).
- Data correction policy: if a new ingestion changes a previously active row for the same natural key, the old row transitions to status='corrected' and a new row is inserted as status='active' (no in-place overwrite), preserving auditability.