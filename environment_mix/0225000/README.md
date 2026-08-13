# DexPaprika — local MCP environment

DexPaprika stores indexed DEX ecosystem data across multiple blockchain networks: networks, DEXes, tokens, liquidity pools, OHLCV candles, and pool transactions. The main workflows are (1) browsing ranked pools by network/DEX/token with pagination & ordering, (2) retrieving pool/token detail pages, (3) fetching time-series OHLCV and transaction feeds, (4) keyword/address search across entities, and (5) returning global ecosystem stats computed from the indexed data.

Repository: https://github.com/coinpaprika/dexpaprika-mcp
Homepage: https://smithery.ai/server/@coinpaprika/dexpaprika-mcp

## Datastore

- `networks.json` — Supported blockchain networks and their metadata; parent for DEXes, tokens, and pools. Powers getNetworks and scopes all network-specific endpoints. (18 rows; fields: ['id', 'name', 'chain_id', 'native_symbol', 'explorer_url', 'icon_url', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'maintenance', 'deprecated']
  - constraint: primary key(id)
  - constraint: unique(name)
  - constraint: chain_id IS NULL OR chain_id >= 1
  - constraint: status IN ('active','maintenance','deprecated')
- `dexes.json` — Decentralized exchanges available on a given network. Powers getNetworkDexes and is referenced by pools for getDexPools and search. (18 rows; fields: ['id', 'network_id', 'slug', 'name', 'website_url', 'factory_address', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'paused', 'deprecated']
  - constraint: primary key(id)
  - constraint: foreign key(network_id) references networks(id)
  - constraint: unique(network_id, slug)
  - constraint: unique(network_id, name)
- `tokens.json` — Token registry per network (contract/mint address). Powers getTokenDetails, token lookups for pools, token-driven pool browsing (getTokenPools), and search. (18 rows; fields: ['id', 'network_id', 'address_normalized', 'address_raw', 'symbol', 'name', 'decimals', 'logo_url', 'is_verified', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'flagged', 'deprecated']
  - constraint: primary key(id)
  - constraint: foreign key(network_id) references networks(id)
  - constraint: unique(network_id, address_normalized)
  - constraint: decimals IS NULL OR (decimals >= 0 AND decimals <= 36)
- `pools.json` — Liquidity pools across networks/DEXes, including ranking metrics and token pair membership. Powers getTopPools/getNetworkPools/getDexPools/getPoolDetails and token-to-pools queries. (19 rows; fields: ['id', 'network_id', 'dex_id', 'address_normalized', 'address_raw', 'token0_id', 'token1_id', 'fee_bps', 'created_on_chain_at', 'price_usd', 'volume_usd_24h', 'transactions_24h', 'last_price_change_usd_24h', 'liquidity_usd', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'disabled']
  - constraint: primary key(id)
  - constraint: foreign key(network_id) references networks(id)
  - constraint: foreign key(dex_id) references dexes(id)
  - constraint: foreign key(token0_id) references tokens(id)
- `pool_market_data.json` — Time-series market data for pools: OHLCV candles and individual transactions. Powers getPoolOHLCV and getPoolTransactions; also supports stats aggregation. (19 rows; fields: ['id', 'pool_id', 'record_type', 'interval', 'bucket_start_at', 'open', 'high', 'low', 'close', 'volume', 'tx_id', 'tx_at', 'tx_type', 'amount0', 'amount1', 'amount_usd', 'raw', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['final', 'reorged', 'invalid']
  - constraint: primary key(id)
  - constraint: foreign key(pool_id) references pools(id)
  - constraint: record_type IN ('ohlcv','tx')
  - constraint: status IN ('final','reorged','invalid')

## Business rules enforced by the tools

- getNetworks returns networks where status != 'deprecated' by default; deprecated networks may be hidden unless explicitly allowed by internal flags.
- getNetworkDexes(network,page,limit) filters dexes by dexes.network_id = networks.id and dexes.status = 'active'; page must be integer >= 0; limit must be integer between 1 and 100.
- getTopPools(page,limit,sort,orderBy) queries pools where status='active' and orders by the mapped field: orderBy=volume_usd -> pools.volume_usd_24h; price_usd -> pools.price_usd; transactions -> pools.transactions_24h; last_price_change_usd_24h -> pools.last_price_change_usd_24h; created_at -> pools.created_on_chain_at (fallback pools.created_at).
- getNetworkPools and getDexPools apply the same ordering mapping as getTopPools and additionally filter by pools.network_id and/or pools.dex_id; sort is asc/desc only.
- getPoolDetails(network,poolAddress,inversed) resolves pool by (pools.network_id = :network AND pools.address_normalized = normalize(:poolAddress)); if inversed=true, the service swaps token0/token1 presentation and inverts any returned price ratio without mutating stored values.
- getTokenDetails(network,tokenAddress) resolves token by (tokens.network_id = :network AND tokens.address_normalized = normalize(:tokenAddress)).
- getTokenPools(network,tokenAddress,page,limit,sort,orderBy,address) resolves the primary token, then returns pools where token0_id=token.id OR token1_id=token.id; if address is provided it must resolve to a token on the same network and pools must contain both tokens.
- getPoolOHLCV(network,poolAddress,start,end,limit,interval,inversed) reads pool_market_data rows where record_type='ohlcv' and matches pool_id and interval; start is required; end defaults to now; end must be <= start + 365 days; limit must be integer 1..366; results are ordered by bucket_start_at ascending and truncated to limit; inversed transforms output prices but does not change stored candles.
- getPoolTransactions(network,poolAddress,page,limit,cursor) reads pool_market_data rows where record_type='tx' and pool_id matches; results are ordered by tx_at desc then tx_id desc; if cursor is provided it must match an existing tx_id for that pool and pagination continues after that cursor; page must be integer >=0 when cursor is absent; limit must be integer 1..100.
- search(query) runs a normalized lookup across: networks.id/name, dexes.slug/name, tokens.address_normalized/symbol/name, pools.address_normalized; address-like queries must prioritize exact address_normalized matches over fuzzy name matches.
- getStats returns aggregates computed from the current tables: counts of active networks/dexes/tokens/pools and optionally summed pools.volume_usd_24h and pools.transactions_24h for active pools; stats must ignore entities with status in ('disabled','deprecated') as applicable.