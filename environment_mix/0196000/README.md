# Scry MCP Server — local MCP environment

This backend powers an MCP search/analytics server that aggregates crypto market data (prices, charts, categories) and DeFi ecosystem data (protocols, TVL, fees, yields, volumes) from external providers like CoinGecko and DeFiLlama. It stores normalized entity metadata (assets, protocols) plus time-series snapshots, and maintains an internal cache lifecycle with refresh jobs and performance stats to serve fast read tools and controlled cache invalidation.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@yongkangc/scry-mcp-raw-js

## Datastore

- `assets.json` — Canonical crypto asset registry used for search, category browsing, and multi-source resolution (symbols, names, contract addresses, provider IDs). (30 rows; fields: ['id', 'asset_type', 'symbol', 'name', 'slug', 'primary_chain', 'contract_address', 'categories', 'provider_ids', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: required(name, asset_type, categories, provider_ids, status, created_at, updated_at)
  - constraint: unique(provider_ids.coingecko_coin_id) WHERE provider_ids.coingecko_coin_id IS NOT NULL
  - constraint: unique(lower(contract_address), lower(primary_chain)) WHERE contract_address IS NOT NULL
  - constraint: unique(upper(symbol), asset_type) WHERE symbol IS NOT NULL
- `protocols.json` — DeFi protocol registry and cached metadata from DeFiLlama for protocol discovery, search, and unified TVL/fees/volume queries. (17 rows; fields: ['id', 'defillama_slug', 'name', 'symbol', 'description', 'category', 'chains', 'tvl_current_usd', 'change_1d_pct', 'change_7d_pct', 'metadata', 'aliases', 'cache_status', 'cache_updated_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `cache_status`: ['fresh', 'stale', 'refreshing', 'error']
  - constraint: required(defillama_slug, name, chains, metadata, aliases, cache_status, status, created_at, updated_at)
  - constraint: unique(defillama_slug)
  - constraint: cache_status IN ('fresh','stale','refreshing','error')
  - constraint: status IN ('active','hidden','disabled')
- `timeseries_points.json` — Normalized time-series storage for prices, TVL, fees/revenue, volumes, yields, stablecoin circulation, and chain TVL. Enables historical tools with date ranges, granularity, sampling, and comparisons. (32 rows; fields: ['id', 'series_type', 'asset_id', 'protocol_id', 'chain', 'pool_id', 'stablecoin_symbol', 'quote_currency', 'bucket_start_at', 'granularity', 'value', 'aux', 'source', 'quality_score', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['final', 'provisional', 'invalid']
  - constraint: required(series_type, bucket_start_at, granularity, value, aux, source, status, created_at, updated_at)
  - constraint: value >= 0 OR series_type IN ('yield_apy')
  - constraint: quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 1)
  - constraint: granularity IN ('hourly','daily','weekly','monthly')
- `cache_entries.json` — General-purpose response cache for external API calls and computed aggregations (e.g., trending coins, top protocols pages, protocol lists) with explicit invalidation and stats. (36 rows; fields: ['id', 'cache_type', 'key', 'tool_name', 'normalized_params', 'payload', 'expires_at', 'last_hit_at', 'hit_count', 'compute_ms', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['valid', 'expired', 'invalidated', 'error']
  - constraint: required(cache_type, key, tool_name, normalized_params, payload, hit_count, status, created_at, updated_at)
  - constraint: unique(cache_type, key)
  - constraint: hit_count >= 0
  - constraint: compute_ms IS NULL OR compute_ms >= 0
- `cache_jobs.json` — Tracks manual and automated cache refresh operations for monitoring, debugging, and performance analysis (supports cache status tools). (32 rows; fields: ['id', 'job_type', 'cache_type', 'requested_by', 'reason', 'started_at', 'finished_at', 'entries_invalidated', 'entries_warmed', 'error_message', 'metrics', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: required(job_type, cache_type, entries_invalidated, entries_warmed, metrics, status, created_at, updated_at)
  - constraint: entries_invalidated >= 0
  - constraint: entries_warmed >= 0
  - constraint: CHECK: finished_at IS NULL OR started_at IS NOT NULL

## Business rules enforced by the tools

- search_assets(query, category, asset_type, limit): query must be non-empty after trimming; limit defaults to 10 and must be within [1,50]; results filter assets.status='active' and match by symbol/name/slug/aliases in provider_ids and categories.
- get_assets_by_category(category, include_prices, vs_currency): category is required; only assets with categories containing category are returned; if include_prices=true, join latest timeseries_points where series_type='asset_price', quote_currency=vs_currency, source='internal_aggregated' preferred else best available by quality_score.
- get_current_price(asset, vs_currency, include_market_data, sources): resolve asset to assets.id by (contract_address+chain) match first, else symbol, else name/slug; if sources is provided, only allow those providers; response is built from freshest cache_entries when valid, else from latest timeseries_points; include_market_data toggles inclusion of market cap/volume/change fields from aux or related series types.
- compare_prices(assets[], vs_currency, sort_by): assets length must be within [2,20]; each asset is resolved as in get_current_price; sorting uses the selected metric (price from series_type='asset_price'; market_cap/volume from aux or related series); missing values sort last.
- get_historical_price(asset, start_date, end_date, granularity, vs_currency, include_volume, include_market_cap, sources): if dates omitted, default start_date=now-30d and end_date=now; enforce start_date<=end_date; cap returned points by server policy using downsampling to requested granularity; sources filtering applies to timeseries_points.source; include_volume/market_cap toggles addition of series_type='asset_volume'/'asset_market_cap' aligned to same buckets.
- coingecko_get_coin_price_detailed(coin_id, vs_currencies, include_*): coin_id must map to assets.provider_ids.coingecko_coin_id or be stored as a synthetic asset record; vs_currencies may be string or array; detailed CoinGecko response may be cached in cache_entries(cache_type='prices', tool_name) keyed by coin_id+vs_currencies+flags.
- coingecko_get_market_chart_detailed(coin_id, vs_currency, days, interval): days accepts number or 'max'; normalize into a bounded time window; store raw provider payload in cache_entries for fast repeat calls and optionally backfill timeseries_points for asset_price.
- coingecko_get_trending_coins(): served primarily from cache_entries(cache_type='trending'); TTL must be short (e.g., hours); if expired, refresh from provider and update cache.
- get_top_protocols(limit, category, chain): limit must be within [1,100]; only protocols.status='active' returned; filter by protocols.category (exact match) and protocols.chains contains chain; order by protocols.tvl_current_usd desc; response can be served from cache_entries(cache_type='protocols').
- defillama_get_protocols_paginated(page, limit, sort_by, sort_order): page>=1 and limit within [1,100]; sorting fields map to protocols.tvl_current_usd, protocols.name, protocols.change_1d_pct, protocols.change_7d_pct; use stable ordering with defillama_slug tie-breaker; may be cached per page/sort.
- defillama_get_protocols(limit, include_warning): limit within [1,50]; include_warning toggles a response field only (no DB effect).
- defillama_search_protocols(query, limit, category_filter, chain_filter, min_tvl): query required; limit within [1,50]; apply filters to protocols.category and protocols.chains; min_tvl filters protocols.tvl_current_usd >= min_tvl; results ordered by tvl desc.
- list_supported_protocols(category, chain, show_details): returns protocols.status='active' optionally filtered by normalized category/chain; show_details toggles inclusion of protocols.metadata and aliases.
- resolve_protocol_name(query, show_alternatives): query required; exact match against defillama_slug or name preferred; otherwise fuzzy match across name/symbol/aliases; if show_alternatives=true return top-N candidates with scores.
- get_historical_tvl(protocol, start_date, end_date, granularity, max_data_points, days_limit, sample_strategy, include_analytics, include_predictions): protocol required and resolved to protocols.id; enforce max_data_points within [10,2000]; if start/end missing use days_limit within [7,1095]; retrieve from timeseries_points(series_type='protocol_tvl', granularity in ['hourly','daily','weekly']) and downsample per sample_strategy; include_analytics/predictions are computed fields and must not mutate stored points.
- defillama_get_chain_historical_tvl(chain, start_timestamp, end_timestamp): chain required; timestamps if provided must satisfy start<=end; data served from timeseries_points(series_type='chain_tvl', chain=chain, granularity='daily'|'hourly' depending on availability).
- defillama_get_protocol_fees_history(protocol, data_type, start_timestamp, end_timestamp): protocol required and resolved by defillama_slug; data_type maps to timeseries_points.series_type ('protocol_fees' or 'protocol_revenue'); time window filters bucket_start_at.
- defillama_get_yields_historical(pool_id, days): pool_id required; days within [1,365]; data served from timeseries_points(series_type='yield_apy', pool_id=pool_id) restricted to last N days.
- defillama_get_stablecoin_historical(stablecoin, chain, start_timestamp, end_timestamp): stablecoin required; if chain provided, filter timeseries_points.chain; series_type='stablecoin_circulation'.
- defillama_compare_protocols_historical(protocols[], start_timestamp, end_timestamp, normalize_to_start): protocols length within [2,5]; each protocol resolved to protocols.id; fetch timeseries_points(series_type='protocol_tvl') aligned to common granularity and intersection of available dates; if normalize_to_start=true scale each series to 100 at first point.
- get_dex_volume(protocol, include_historical, include_breakdown, days_limit): protocol required; days_limit within [7,365]; spot volume served from timeseries_points(series_type='dex_spot_volume'); if include_breakdown=true include chain-level breakdown from timeseries_points.aux.chain_breakdown or per-chain rows (chain populated) depending on ingestion strategy.
- get_derivatives_overview(chain, limit, include_breakdown, min_volume_24h): limit within [1,100]; compute 24h volume from latest derivatives_volume points; optional chain filter uses protocols.chains contains chain or per-chain breakdown; min_volume_24h filters computed metric; cacheable under cache_type='volumes'.
- get_derivatives_volume(protocol, include_historical, days_limit): protocol required; days_limit within [7,365]; served from timeseries_points(series_type='derivatives_volume').
- defillama_get_cache_status(include_details): aggregates cache_entries by cache_type/status and summarizes TTL expirations; include_details toggles inclusion of top keys, hit rates, and last_hit_at distributions and latest cache_jobs.
- defillama_refresh_cache(cache_type): creates a cache_jobs row (job_type='refresh_cache', cache_type in ['protocols','all']) and transitions it queued->running; invalidates cache_entries by setting status='invalidated' for the targeted cache types; for cache_type='protocols' additionally marks protocols.cache_status='refreshing' until refreshed.
- defillama_search_cached_protocols(query, limit, show_details): query required; search is executed against protocols table only (no external calls) and must not create cache entries; show_details toggles protocols.metadata inclusion.
- defillama_analyze_cache_performance(show_recommendations): reads cache_entries and cache_jobs to compute hit ratios, p95 compute_ms, and identifies hot keys; show_recommendations toggles generation of advisory text only.
- ping(message): does not read or mutate domain tables; may log at application layer only (no persistence required).