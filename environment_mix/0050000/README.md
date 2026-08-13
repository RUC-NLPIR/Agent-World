# Finance MCP Server — local MCP environment

This backend stores tracked financial instruments (stocks/crypto), cached market price snapshots by period, and cached news articles tied to each instrument. The main workflows are: resolve a requested ticker to an instrument, fetch/refresh price and news from upstream providers, persist normalized snapshots/articles, and serve responses from cache while tracking API usage and enforcing quotas.

Repository: https://github.com/Otman404/finance-mcp-server
Homepage: https://smithery.ai/server/@Otman404/finance-mcp-server

## Datastore

- `api_clients.json` — Represents a calling client (API key owner) used for quota enforcement, auditing, and abuse control. Even if the MCP server is locally used, production deployments typically gate with client tokens. (12 rows; fields: ['id', 'name', 'api_key_hash', 'status', 'requests_per_minute', 'requests_per_day', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(api_key_hash)
  - constraint: requests_per_minute BETWEEN 1 AND 6000
  - constraint: requests_per_day BETWEEN 1 AND 1000000
- `instruments.json` — Canonical financial instruments resolved from user-provided tickers. Supports stocks and crypto with a normalized symbol plus optional exchange and provider identifiers. (18 rows; fields: ['id', 'symbol', 'asset_type', 'exchange', 'name', 'provider', 'provider_instrument_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'delisted']
  - constraint: unique(symbol, exchange, asset_type)
  - constraint: symbol length BETWEEN 1 AND 32
- `price_snapshots.json` — Cached price responses for an instrument and period. This backs get_price(ticker, period) by returning the freshest snapshot within TTL or triggering an upstream refresh to insert a new row. (17 rows; fields: ['id', 'instrument_id', 'period', 'currency', 'as_of', 'payload', 'fetch_status', 'error_message', 'source', 'created_at', 'updated_at'])
  - lifecycle `fetch_status`: ['fresh', 'stale', 'error']
  - constraint: fk(instrument_id) references instruments(id) on delete cascade
  - constraint: unique(instrument_id, period, as_of)
  - constraint: as_of <= now() + interval '5 minutes'
- `news_articles.json` — News articles associated with an instrument. This backs get_news(ticker, count) by selecting most recent articles for the instrument, optionally refreshed from upstream. (18 rows; fields: ['id', 'instrument_id', 'title', 'url', 'publisher', 'summary', 'published_at', 'language', 'source', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'hidden', 'deleted']
  - constraint: fk(instrument_id) references instruments(id) on delete cascade
  - constraint: unique(url)
  - constraint: published_at <= now() + interval '5 minutes'
- `request_logs.json` — Append-only audit/usage log of tool calls. Enables rate limiting, daily quota enforcement, and debugging of upstream errors. (19 rows; fields: ['id', 'client_id', 'tool_name', 'ticker', 'period', 'count', 'instrument_id', 'cache_hit', 'status', 'http_status', 'latency_ms', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ok', 'not_found', 'rate_limited', 'upstream_error', 'invalid_argument']
  - constraint: fk(client_id) references api_clients(id) on delete set null
  - constraint: fk(instrument_id) references instruments(id) on delete set null
  - constraint: count IS NULL OR count BETWEEN 1 AND 100
  - constraint: latency_ms >= 0

## Business rules enforced by the tools

- get_price must resolve the input ticker to instruments.symbol (case-insensitive); if no match exists, it may create an instruments row with status=active only if the upstream provider successfully resolves it, otherwise it must return status=not_found and log the request.
- get_price period defaults to '1d' and must be one of: 1d, 5d, 1mo, 3mo, 6mo, 1y, 5y, max; invalid values must return status=invalid_argument and be logged.
- get_news count defaults to 5 and must be between 1 and 100 inclusive; invalid values must return status=invalid_argument and be logged.
- For get_price, the server should prefer the newest price_snapshots row for (instrument_id, period) with fetch_status=fresh and as_of within the configured TTL; if none exists, it must fetch upstream and insert a new snapshot row with fetch_status=fresh or fetch_status=error.
- For get_news, the server must return up to count news_articles rows with status=active for the instrument ordered by published_at desc; if cache is empty or stale per TTL, it should fetch upstream, upsert by url uniqueness, and then re-query.
- Uniqueness must be enforced for instruments(symbol, exchange, asset_type), price_snapshots(instrument_id, period, as_of), and news_articles(url) to prevent duplicate ingestion.
- If client_id is present, each request must be rate-limited to api_clients.requests_per_minute and api_clients.requests_per_day; exceeding either must return status=rate_limited and still write a request_logs row with cache_hit=false.
- When upstream fetching fails, the server must not delete existing cached data; it may serve stale data (setting request_logs.cache_hit=true and status=ok) only if a snapshot/article set exists within a maximum-staleness window, otherwise it must return upstream_error.