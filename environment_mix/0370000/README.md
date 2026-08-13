# Crypto Price & Market Analysis Server — local MCP environment

This backend stores cryptocurrency reference data and continuously ingests market snapshots (current price + 24h stats), exchange-level market metrics, and OHLCV candle series for historical analysis. The main workflows are: resolve a requested symbol to an asset, read the latest price snapshot, read a recent set of exchange metrics for market analysis, and read candles over a requested timeframe for historical analysis.

Repository: https://github.com/truss44/mcp-crypto-price
Homepage: https://smithery.ai/server/@truss44/mcp-crypto-price

## Datastore

- `crypto_assets.json` — Canonical cryptocurrency assets that can be queried by symbol (e.g., BTC, ETH). Acts as the reference table for all market data. (30 rows; fields: ['id', 'symbol', 'name', 'coingecko_id', 'is_active', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'merged']
  - constraint: unique(symbol)
  - constraint: symbol = upper(symbol)
  - constraint: symbol length between 2 and 10
  - constraint: is_active = true implies status = 'active'
- `price_snapshots.json` — Latest and historical point-in-time price + 24h stats for each asset. Used by get-crypto-price; latest row by observed_at is returned. (31 rows; fields: ['id', 'asset_id', 'currency', 'price', 'market_cap', 'volume_24h', 'price_change_24h', 'price_change_pct_24h', 'high_24h', 'low_24h', 'observed_at', 'source', 'ingestion_status', 'created_at', 'updated_at'])
  - lifecycle `ingestion_status`: ['complete', 'partial', 'error']
  - constraint: fk(asset_id) references crypto_assets(id)
  - constraint: unique(asset_id, currency, observed_at, source)
  - constraint: price >= 0
  - constraint: market_cap is null or market_cap >= 0
- `exchanges.json` — Exchange reference data used to label top exchanges in market analysis. (30 rows; fields: ['id', 'code', 'name', 'country', 'website_url', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: unique(code)
  - constraint: code = lower(code)
  - constraint: code length between 2 and 32
- `exchange_market_metrics.json` — Per-asset, per-exchange market metrics (e.g., volume distribution) used by get-market-analysis to compute top exchanges and relative shares for a time window around observed_at. (34 rows; fields: ['id', 'asset_id', 'exchange_id', 'currency', 'volume_24h', 'liquidity_score', 'observed_at', 'source', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['valid', 'superseded', 'error']
  - constraint: fk(asset_id) references crypto_assets(id)
  - constraint: fk(exchange_id) references exchanges(id)
  - constraint: unique(asset_id, exchange_id, currency, observed_at, source)
  - constraint: volume_24h >= 0
- `candles.json` — OHLCV candle series for historical analysis. Used by get-historical-analysis with interval and days to slice by [end_at - days, end_at]. (30 rows; fields: ['id', 'asset_id', 'currency', 'interval', 'open', 'high', 'low', 'close', 'volume', 'start_at', 'end_at', 'source', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['valid', 'corrected', 'error']
  - constraint: fk(asset_id) references crypto_assets(id)
  - constraint: unique(asset_id, currency, interval, start_at, source)
  - constraint: open >= 0 and high >= 0 and low >= 0 and close >= 0
  - constraint: high >= greatest(open, close, low)

## Business rules enforced by the tools

- Tool get-crypto-price(symbol) must resolve symbol case-insensitively to crypto_assets.symbol; if no active asset exists (status != 'active' or is_active = false), return not-found.
- Tool get-crypto-price(symbol) returns the most recent price_snapshots row for the resolved asset with ingestion_status in ('complete','partial') ordered by observed_at desc; if only 'error' exists, return not-found.
- Tool get-market-analysis(symbol) must resolve symbol as above and compute top exchanges by summing exchange_market_metrics.volume_24h for the latest observed_at per (asset_id, exchange_id) where status='valid'; top list is limited to a server-side maximum (e.g., 10) even if more exist.
- Tool get-market-analysis(symbol) must compute volume distribution shares as exchange_volume / total_volume for the selected metric set; if total_volume = 0, shares must be omitted or set to 0 and no division-by-zero occurs.
- Tool get-historical-analysis(symbol, interval, days) must validate interval in {m5,m15,m30,h1,h2,h6,h12,d1}; if omitted, treat as 'h1'.
- Tool get-historical-analysis(symbol, interval, days) must validate days is within [1,30]; if omitted, treat as 7; non-integer values are allowed by schema but must be coerced or rejected—backend enforces days is an integer within [1,30].
- Tool get-historical-analysis(symbol, interval, days) queries candles for the resolved asset where interval matches and status in ('valid','corrected'), within [now() - interval_to_duration(days), now()], ordered by start_at asc; if gaps exist, analysis must still succeed using available candles.
- Ingestion must not create duplicate rows violating uniqueness constraints; on conflict for the same natural key (asset_id, currency, interval/start_at/source or asset_id/exchange_id/currency/observed_at/source), it must upsert and advance lifecycle status only via declared transitions.