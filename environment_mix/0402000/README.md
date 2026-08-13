# Financial Datasets Server — local MCP environment

This backend stores normalized market data and fundamentals for public companies and cryptocurrencies, plus related news and SEC filings. The main workflows are (1) resolving a requested ticker to an instrument, then (2) reading time-series prices and periodic financial statements, and (3) returning latest quotes, company news, and SEC filing metadata/doc links with simple limits and filters.

Repository: https://github.com/jaswgq/mcp-server
Homepage: https://smithery.ai/server/@jaswgq/mcp-server

## Datastore

- `instruments.json` — Master security/asset directory for equities and cryptocurrencies, used to resolve tickers and drive all downstream queries. (18 rows; fields: ['id', 'asset_class', 'ticker', 'exchange', 'name', 'currency', 'sector', 'industry', 'cik', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'delisted']
  - constraint: unique(asset_class, upper(ticker))
  - constraint: ticker != ''
  - constraint: asset_class = 'equity' implies (cik is null or cik ~ '^[0-9]{1,10}$')
- `price_bars.json` — Time-series OHLCV bars for both equities and crypto across supported intervals; powers historical price tools and can also backfill latest price. (16 rows; fields: ['id', 'instrument_id', 'interval', 'interval_multiplier', 'ts', 'open', 'high', 'low', 'close', 'volume', 'vwap', 'data_status', 'source', 'created_at', 'updated_at'])
  - lifecycle `data_status`: ['final', 'preliminary', 'corrected']
  - constraint: interval_multiplier >= 1 and interval_multiplier <= 1440
  - constraint: open >= 0 and high >= 0 and low >= 0 and close >= 0
  - constraint: high >= greatest(open, close, low) and low <= least(open, close, high)
  - constraint: unique(instrument_id, interval, interval_multiplier, ts)
- `financial_statements.json` — Normalized financial statements (income statement, balance sheet, cash flow) by company and period; used by statement retrieval tools. (17 rows; fields: ['id', 'instrument_id', 'statement_type', 'period', 'fiscal_year', 'fiscal_quarter', 'period_end_date', 'reported_currency', 'data', 'status', 'source', 'created_at', 'updated_at'])
  - lifecycle `status`: ['published', 'restated', 'deprecated']
  - constraint: instruments.asset_class for instrument_id must be 'equity' (enforced in service layer or FK via partial index strategy)
  - constraint: period = 'quarterly' implies fiscal_quarter between 1 and 4
  - constraint: period in ('annual','ttm') implies fiscal_quarter is null
  - constraint: unique(instrument_id, statement_type, period, period_end_date, status) where status != 'deprecated'
- `company_news.json` — News articles associated to a company ticker; used by get_company_news. (17 rows; fields: ['id', 'instrument_id', 'published_at', 'title', 'summary', 'url', 'source_name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: unique(instrument_id, url)
  - constraint: url != ''
  - constraint: title != ''
- `sec_filings.json` — SEC filing metadata and document links by company, supporting filtering by filing type and limiting results. (17 rows; fields: ['id', 'instrument_id', 'filing_type', 'accession_number', 'filed_at', 'report_period_end_date', 'primary_document_url', 'index_url', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'superseded', 'removed']
  - constraint: unique(accession_number)
  - constraint: unique(instrument_id, filing_type, filed_at, accession_number)
  - constraint: filing_type != ''
  - constraint: accession_number != ''

## Business rules enforced by the tools

- Ticker lookup is case-insensitive: tools must resolve input ticker by instruments.ticker using upper-casing and must error if no active instrument exists.
- get_available_crypto_tickers returns instruments where asset_class='crypto' and status='active', ordered by ticker.
- get_current_stock_price returns the latest available price_bars row for the equity instrument, preferring interval='minute' with interval_multiplier=1; if none exists, fall back to the most recent row across any interval, and must not return bars with data_status='removed' (not modeled) or missing instrument.
- get_current_crypto_price follows the same latest-bar logic as get_current_stock_price but for asset_class='crypto'.
- get_historical_stock_prices and get_historical_crypto_prices must filter price_bars by instrument_id, interval, interval_multiplier, and ts between start_date (inclusive) and end_date (inclusive), and must enforce start_date <= end_date.
- For historical price tools, interval must be one of minute/hour/day/week/month; interval_multiplier must be an integer between 1 and 1440.
- get_income_statements/get_balance_sheets/get_cash_flow_statements must read financial_statements by instrument_id, statement_type, period, status in ('published','restated'), ordered by period_end_date desc, applying limit default=4 when omitted.
- Financial statements may only be stored for equity instruments; service must reject attempts (if any ingestion path exists) to attach statements to crypto instruments.
- get_company_news returns company_news for the equity instrument where status='active', ordered by published_at desc; duplicates must be prevented by unique(instrument_id,url).
- get_sec_filings returns sec_filings for the equity instrument where status in ('available','superseded'), optionally filtered by filing_type, ordered by filed_at desc, applying limit default=10 when omitted.
- All FK references must exist at read time: rows in price_bars/financial_statements/company_news/sec_filings referencing a non-existent instrument must be impossible due to FK integrity.