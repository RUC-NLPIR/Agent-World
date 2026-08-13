# CoinGecko API Server — local MCP environment

This backend powers a CoinGecko-like read API by maintaining a local cache of coins, their market snapshots, and derived time-series (OHLC). It also tracks search queries and trending aggregates to serve fast search endpoints while refreshing data from upstream sources on a schedule.

Repository: https://github.com/nic0xflamel/coingecko-mcp-server
Homepage: https://smithery.ai/server/@nic0xflamel/coingecko-mcp-server

## Datastore

- `coins.json` — Canonical coin metadata and identifier mappings (id/symbol/name, web slug, platform/contract mappings, and optional rich profile blobs used by the coin-by-id endpoint). (20 rows; fields: ['id', 'coingecko_id', 'symbol', 'name', 'web_slug', 'asset_platform_id', 'platforms', 'detail_platforms', 'block_time_in_minutes', 'hashing_algorithm', 'categories', 'preview_listing', 'public_notice', 'additional_notices', 'localization', 'description', 'links', 'image', 'country_origin', 'genesis_date', 'sentiment_votes_up_percentage', 'sentiment_votes_down_percentage', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'delisted', 'inactive']
  - constraint: unique(coingecko_id)
  - constraint: unique(lower(symbol), lower(name), coingecko_id) -- prevent accidental duplicate identity rows
  - constraint: symbol <> ''
  - constraint: name <> ''
- `coin_categories.json` — Category catalog used for filtering in coins/markets and for search results. Holds both list-style (category_id, name) and market-cap rollups when available. (18 rows; fields: ['id', 'category_id', 'name', 'content', 'market_cap', 'market_cap_change_24h', 'volume_24h', 'top_3_coins_id', 'top_3_coins', 'upstream_updated_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated']
  - constraint: unique(category_id)
  - constraint: name <> ''
  - constraint: category_id <> ''
  - constraint: market_cap is null or market_cap >= 0
- `coin_market_snapshots.json` — Denormalized per-coin market data snapshots by vs_currency, used to serve /simple/price and /coins/markets quickly and to back derived series like sparkline and OHLC. (20 rows; fields: ['id', 'coin_id', 'vs_currency', 'image_url', 'current_price', 'market_cap', 'market_cap_rank', 'fully_diluted_valuation', 'total_volume', 'high_24h', 'low_24h', 'price_change_24h', 'price_change_percentage_1h', 'price_change_percentage_24h', 'price_change_percentage_7d', 'price_change_percentage_14d', 'price_change_percentage_30d', 'price_change_percentage_200d', 'price_change_percentage_1y', 'market_cap_change_24h', 'market_cap_change_percentage_24h', 'circulating_supply', 'total_supply', 'max_supply', 'ath', 'ath_change_percentage', 'ath_date', 'atl', 'atl_change_percentage', 'atl_date', 'roi', 'sparkline_7d_prices', 'last_updated', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'error']
  - constraint: unique(coin_id, vs_currency) -- current snapshot per coin per currency
  - constraint: current_price >= 0
  - constraint: market_cap is null or market_cap >= 0
  - constraint: total_volume is null or total_volume >= 0
- `coin_ohlc.json` — Precomputed OHLC candles for coins by vs_currency and standard day ranges (1/7/14/30/90/180/365) used by /coins/{id}/ohlc. (19 rows; fields: ['id', 'coin_id', 'vs_currency', 'days', 'granularity_minutes', 'candles', 'last_updated', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'error']
  - constraint: unique(coin_id, vs_currency, days)
  - constraint: granularity_minutes in (5, 15, 30, 60, 240, 1440) -- typical resolutions
  - constraint: vs_currency = lower(vs_currency)
  - constraint: json_array_length(candles) <= 10000 -- hard safety limit for storage/response size
- `search_queries.json` — Stores search query requests and response summaries for /search and supports rolling trending calculations for /search/trending. (18 rows; fields: ['id', 'query', 'normalized_query', 'ip_hash', 'user_agent_hash', 'result_coins', 'result_exchanges', 'result_categories', 'result_nfts', 'result_icos', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['completed', 'failed']
  - constraint: query <> ''
  - constraint: normalized_query = lower(trim(query))
  - constraint: json_array_length(result_coins) is null or json_array_length(result_coins) <= 50
  - constraint: json_array_length(result_exchanges) is null or json_array_length(result_exchanges) <= 50
- `trending_snapshots.json` — Cached output for /search/trending including trending coins, NFTs, and categories. Updated on a schedule using aggregated search activity and/or upstream feeds. (18 rows; fields: ['id', 'window', 'coins', 'nfts', 'categories', 'computed_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded']
  - constraint: unique(window, status) where status = 'active' -- only one active snapshot per window
  - constraint: json_array_length(coins) <= 50
  - constraint: json_array_length(nfts) <= 50
  - constraint: json_array_length(categories) <= 50

## Business rules enforced by the tools

- API-coins-list: If include_platform=false, the response must omit platforms; if include_platform=true, platforms must be populated from coins.platforms (or empty object if unknown).
- API-simple-price: vs_currencies is required and must be parsed as lowercase comma-separated values; ids/names/symbols are optional selectors. If multiple selectors are provided, ids takes precedence, then names, then symbols; results are keyed by coin coingecko_id.
- API-simple-price: include_market_cap/include_24hr_vol/include_24hr_change/include_last_updated_at control which fields are returned from coin_market_snapshots (market_cap, total_volume, price_change_percentage_24h or price_change_24h, last_updated unix seconds). Unrequested fields must be omitted.
- API-simple-price & API-coins-markets: precision must be applied as rounding to the requested decimal places (or 'full' = no rounding); rounding applies to all numeric quote-currency values in the response.
- API-coins-markets: vs_currency is required. Filtering by category must use coin_categories.category_id and coins.categories membership (or a maintained mapping) so only coins in that category are returned.
- API-coins-markets: per_page must be in [1,250] and page must be >= 1; default per_page=100 and page=1 if omitted. Sorting must follow order enum; unknown values are rejected.
- API-coins-id: id must match an existing coins.coingecko_id; otherwise return not found. localization/tickers/market_data/community_data/developer_data/sparkline flags must control which corresponding JSON blobs are included in the response; sparkline uses coin_market_snapshots.sparkline_7d_prices when available.
- API-coins-id-ohlc: days must be one of the allowed enums and vs_currency required. The response must be taken from coin_ohlc.candles for the matching (coin_id, vs_currency, days); if missing, the system may compute/fetch and store it, transitioning status from stale/error to fresh on success.
- API-search-data: Each request must be recorded in search_queries with normalized_query=lower(trim(query)). The response must be built from indexed lookups over coins.coingecko_id/symbol/name and coin_categories.name/category_id, with result arrays capped to a maximum of 50 items each.
- API-trending-search: Must return the latest trending_snapshots row where status='active' and window='24h' (or service default). If none exists, return an empty but well-formed structure with coins/nfts/categories as empty arrays.
- FK integrity: coin_market_snapshots.coin_id and coin_ohlc.coin_id must reference existing coins.id; deleting a coin is prohibited while dependent snapshots exist (restrict).
- Staleness: coin_market_snapshots.status must become 'stale' when now - last_updated exceeds a configured TTL per currency (e.g., 120s for usd); clients still receive stale data unless status='error' and no previous fresh/stale snapshot exists.