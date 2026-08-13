# CoinMarketCap MCP — local MCP environment

This backend powers an MCP wrapper around the CoinMarketCap API by storing a normalized cache of reference entities (cryptocurrencies, fiats, exchanges, DEX networks/pairs), time-series market data (quotes, OHLCV, indices), and the operational data needed to serve clients (API keys, request logs, and cached upstream responses). Read tools primarily query cached entities and time-series tables, while keyInfo and quota enforcement read from API key and usage tables; cache entries can be refreshed asynchronously from upstream.

Repository: https://github.com/shinzo-labs/coinmarketcap-mcp
Homepage: https://smithery.ai/server/@shinzo-labs/coinmarketcap-mcp

## Datastore

- `api_keys.json` — Client API keys for the MCP service, including quota configuration and usage rollups needed to implement keyInfo and enforce request limits. (17 rows; fields: ['id', 'key_hash', 'key_prefix', 'label', 'status', 'plan', 'requests_per_minute_limit', 'requests_per_day_limit', 'monthly_credit_limit', 'requests_today', 'requests_this_minute', 'credits_month_to_date', 'last_request_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: requests_per_minute_limit >= 0
  - constraint: requests_per_day_limit >= 0
- `request_logs.json` — Immutable audit log of tool invocations and upstream calls. Supports usage stats for keyInfo and operational debugging; also enables cache hit-rate and per-tool credit accounting. (18 rows; fields: ['id', 'api_key_id', 'tool_name', 'request_params', 'cache_key', 'cache_hit', 'upstream_http_status', 'credits_charged', 'duration_ms', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: credits_charged >= 0
  - constraint: duration_ms >= 0
  - constraint: upstream_http_status is null or (upstream_http_status >= 100 and upstream_http_status <= 599)
- `asset_directory.json` — Canonical directory of assets and venues needed across tools: cryptocurrencies, fiat currencies, CEX exchanges, DEX exchanges, and DEX networks. Powers map/info endpoints and provides FK targets for quotes, OHLCV, and holdings. (18 rows; fields: ['id', 'entity_type', 'upstream_id', 'slug', 'symbol', 'name', 'listing_status', 'rank', 'category', 'tags', 'metadata', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['current', 'stale', 'deleted']
  - constraint: unique(entity_type, upstream_id)
  - constraint: unique(entity_type, slug) where slug is not null
  - constraint: unique(entity_type, symbol) where symbol is not null and entity_type in ('cryptocurrency','fiat')
  - constraint: rank is null or rank >= 1
- `categories_and_memberships.json` — Coin categories and the many-to-many membership between categories and cryptocurrencies. Supports cryptoCategories and cryptoCategory (including paginated member lists). (21 rows; fields: ['id', 'upstream_id', 'name', 'slug', 'description', 'num_tokens', 'status', 'last_synced_at', 'memberships', 'created_at', 'updated_at'])
  - lifecycle `status`: ['current', 'stale', 'deleted']
  - constraint: unique(upstream_id)
  - constraint: unique(slug) where slug is not null
  - constraint: num_tokens is null or num_tokens >= 0
  - constraint: memberships items must reference asset_directory rows with entity_type='cryptocurrency' (enforced in service layer)
- `market_data.json` — Time-series and snapshot market data used to answer listings, latest quotes, global metrics, index values, fear/greed values, DEX pair quotes/OHLCV/trades, exchange assets, and price conversion. Data is keyed by entity_type + entity identifiers + as_of timestamp and optional conversion currency. (19 rows; fields: ['id', 'record_type', 'primary_asset_id', 'secondary_asset_id', 'contract_address', 'as_of', 'time_period', 'interval', 'convert_symbol', 'convert_upstream_id', 'numeric_fields', 'aux_fields', 'status', 'source_request_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'superseded', 'deleted']
  - constraint: fk(primary_asset_id) references asset_directory(id) on delete restrict
  - constraint: fk(secondary_asset_id) references asset_directory(id) on delete restrict
  - constraint: fk(source_request_id) references request_logs(id) on delete set null
  - constraint: as_of is not null
- `cached_responses.json` — HTTP-level cached upstream responses keyed by tool name and normalized parameters. This allows fast responses for read-heavy tools and provides the raw payload needed to rebuild normalized tables. (21 rows; fields: ['id', 'tool_name', 'params_fingerprint', 'request_params', 'response_body', 'http_status', 'etag', 'expires_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['valid', 'expired', 'purged']
  - constraint: unique(tool_name, params_fingerprint)
  - constraint: http_status >= 100 and http_status <= 599
  - constraint: expires_at > created_at
  - constraint: json_valid(request_params)

## Business rules enforced by the tools

- Every tool invocation must create exactly one request_logs row with tool_name matching the tool and request_params containing only schema-allowed properties (additionalProperties=false).
- Requests must be rejected when api_keys.status != 'active'.
- Rate limiting: if requests_this_minute >= requests_per_minute_limit (when limit > 0) then new requests are denied; counter window resets on minute boundary. Similarly, if requests_today >= requests_per_day_limit (when limit > 0) deny; counter resets at UTC day boundary.
- Credit limiting: if credits_month_to_date + credits_charged_for_request > monthly_credit_limit (when limit > 0) deny; month resets at UTC month boundary.
- cached_responses entries are addressable by (tool_name, params_fingerprint); a response is a cache hit only when status='valid' and expires_at > now().
- cryptoCategories reads categories_and_memberships filtered by upstream_id (id) OR slug (slug); pagination uses start/limit over deterministic order (e.g., upstream_id asc).
- cryptoCategory requires id and returns category plus member cryptocurrencies; members are resolved from categories_and_memberships.memberships with pagination start/limit, and optional convert/convert_id affects pricing fields sourced from market_data rows with matching convert_symbol/convert_upstream_id.
- cryptoCurrencyMap returns asset_directory rows where entity_type='cryptocurrency', filtered by listing_status and symbol, sorted per request; aux controls which fields from metadata are projected.
- fiatMap returns asset_directory rows where entity_type='fiat', optionally filtering out metal-backed fiats unless include_metals=true (derived from metadata.type or tags).
- exchangeMap returns asset_directory rows where entity_type='exchange', filtered by listing_status and/or slug; pagination via start/limit.
- dexNetworksList returns asset_directory rows where entity_type='dex_network' with pagination and sort/sort_dir applied to upstream_id or name.
- getCryptoMetadata resolves cryptocurrencies by symbol OR id OR slug OR address; address matches within asset_directory.metadata.platform.contract_address or metadata.contract_addresses; if skip_invalid=true, unresolved identifiers are omitted rather than causing an error.
- cryptoQuotesLatest and allCryptocurrencyListings source pricing and market fields from market_data.record_type in ('crypto_quote_latest','crypto_listings_latest_row'); numeric filters (price_min/max, market_cap_min/max, etc.) apply to numeric_fields; sort and sort_dir must match the allowed enums.
- globalMetricsLatest reads the newest market_data row with record_type='global_metrics_latest' and matching convert params if provided.
- cmc100IndexLatest reads the newest market_data row with record_type='cmc100_index_value' plus associated constituents from rows with record_type='cmc100_index_constituent' at the same as_of timestamp.
- cmc100IndexHistorical reads market_data rows with record_type='cmc100_index_value' filtered by time_start/time_end or count and interval; interval must be one of ['5m','15m','daily'].
- fearAndGreedLatest reads the newest market_data row with record_type='fear_greed_value'; historical uses start/limit to page over descending as_of.
- dexInfo and exchangeInfo read from asset_directory (entity_type='dex' or 'exchange') by upstream_id and/or slug; aux controls which metadata sections are returned.
- dexListingsLatest reads market_data rows with record_type='dex_listing_latest_row' joined to asset_directory entity_type='dex'; supports sort/sort_dir/type filters with allowed enums; convert_id selects converted numeric_fields when present.
- dexSpotPairsLatest reads market_data rows with record_type='dex_spot_pair_latest_row' and filters on network/dex/base/quote identifiers plus min/max filters over numeric_fields; scroll_id is mapped to pagination cursor derived from (as_of,id) and reverse_order toggles direction.
- dexPairsQuotesLatest, dexPairsOhlcvLatest, dexPairsOhlcvHistorical, and dexPairsTradeLatest filter by contract_address and network id/slug; if skip_invalid is truthy, missing pairs return empty results; otherwise an error is raised.
- priceConversion requires amount; it reads the latest crypto quote for the source (id or symbol) and conversion rate for convert/convert_id, then stores the computed result only as a transient response (may be cached in cached_responses but is not persisted into market_data unless configured).
- getPostmanCollection returns a static document; it may be served from cached_responses with a long TTL and does not require upstream access.