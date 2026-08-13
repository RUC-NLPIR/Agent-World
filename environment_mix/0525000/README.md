# Moralis API Server — local MCP environment

This backend powers a Web3 data API that serves read-heavy endpoints for NFTs, ERC20 tokens, DEX pairs/swaps, wallet activity, and entity/label intelligence across multiple chains. It stores normalized chain assets (tokens, NFT collections/items), time-series market/analytics, and an indexed stream of on-chain events (transfers, swaps, trades) that are aggregated into wallet-level and discovery/search views.

Repository: https://github.com/MoralisWeb3/moralis-mcp-server
Homepage: https://smithery.ai/server/@MoralisWeb3/moralis-mcp-server

## Datastore

- `chains.json` — Supported blockchain networks and their canonical identifiers used across all API reads/aggregations. (30 rows; fields: ['id', 'chain_key', 'chain_type', 'native_symbol', 'display_name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'degraded', 'disabled']
  - constraint: unique(chain_key)
  - constraint: native_symbol <> ''
  - constraint: display_name <> ''
- `addresses.json` — Chain-scoped addresses and ENS mappings used for wallet-centric reads, ownership, and entity/address labeling. (33 rows; fields: ['id', 'chain_id', 'address', 'address_kind', 'ens_name', 'ens_resolved_address', 'first_seen_at', 'last_seen_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'blacklisted', 'suppressed']
  - constraint: unique(chain_id, address)
  - constraint: address <> ''
  - constraint: ens_name is null OR chain_id references an evm chain
  - constraint: ens_name is null OR ens_name like '%.eth'
- `entities.json` — Off-chain identity and labeling layer (organizations, exchanges, known wallets) mapped to one or many chain addresses and categories; used by entity search and token owner intelligence. (30 rows; fields: ['id', 'name', 'description', 'logo_url', 'external_links', 'category', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: unique(name, category)
  - constraint: name <> ''
- `entity_addresses.json` — Join table mapping entities to one or many chain addresses with optional role/label metadata; drives searchEntities/getEntity and token owner labeling. (32 rows; fields: ['id', 'entity_id', 'address_id', 'label', 'role', 'confidence', 'created_at', 'updated_at'])
  - constraint: unique(entity_id, address_id)
  - constraint: confidence >= 0 AND confidence <= 1
  - constraint: fk(entity_id) references entities.id on delete cascade
  - constraint: fk(address_id) references addresses.id on delete cascade
- `assets.json` — Chain assets: fungible tokens (ERC20/native) and NFT collections/items. Stores core metadata plus latest known pricing/market fields used by discovery and wallet valuation. (38 rows; fields: ['id', 'chain_id', 'asset_type', 'contract_address_id', 'token_id', 'name', 'symbol', 'decimals', 'logo_url', 'metadata', 'spam_status', 'latest_price_native', 'latest_price_usd', 'market_cap_usd', 'liquidity_usd', 'fdv_usd', 'floor_price_native', 'floor_price_usd', 'floor_price_refreshed_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'hidden']
  - constraint: unique(chain_id, asset_type, contract_address_id, token_id)
  - constraint: decimals is null OR (decimals >= 0 AND decimals <= 30)
  - constraint: latest_price_usd is null OR latest_price_usd >= 0
  - constraint: market_cap_usd is null OR market_cap_usd >= 0
- `events.json` — Unified indexed on-chain event ledger for transfers, swaps, NFT trades, approvals, and decoded transactions; supports wallet history, token transfers, swap endpoints, ownership inference, and time-series aggregates. (32 rows; fields: ['id', 'chain_id', 'event_type', 'block_number', 'block_hash', 'block_timestamp', 'transaction_hash', 'log_index', 'from_address_id', 'to_address_id', 'contract_address_id', 'asset_id', 'counter_asset_id', 'token_id', 'amount_raw', 'amount_decimal', 'value_usd', 'marketplace', 'metadata', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['confirmed', 'reorged', 'pending', 'dropped']
  - constraint: block_number >= 0
  - constraint: log_index is null OR log_index >= 0
  - constraint: value_usd is null OR value_usd >= 0
  - constraint: unique(chain_id, transaction_hash, log_index, event_type)

## Business rules enforced by the tools

- All reads are chain-scoped: any tool that accepts or implies a chain must filter by chains.chain_key mapped to chains.id, and then use that chains.id across addresses/assets/events joins.
- resolveAddress returns addresses.ens_name where chain is EVM and addresses.address matches input; if no ENS exists, return null/empty without creating a new mapping.
- resolveEnsDomain returns addresses.ens_resolved_address by looking up a row where addresses.ens_name equals the provided domain; if not present, return null/empty without mutation.
- getLatestBlockNumber returns max(events.block_number) for events.event_type='block' and status='confirmed' on the requested chain.
- getDateToBlock finds the confirmed block event with block_timestamp closest to the provided date on the requested chain; ties resolve to the lower block_number.
- Wallet endpoints (getWalletHistory/getWalletStats/getWalletActiveChains/getWalletApprovals) must treat a wallet as an addresses row with address_kind='wallet' (create-on-read allowed for addresses only) and join events where from_address_id or to_address_id equals that wallet address_id; approvals are events.event_type='approval' filtered to status='confirmed'.
- Token transfer endpoints (getTokenTransfers/getWalletTokenBalancesPrice) use events.event_type='token_transfer' for ERC20 and events.event_type='native_transfer' for native; balances are derived from summing confirmed transfers up to a block cut (not stored as a separate balance table in this minimal schema).
- NFT ownership endpoints (getNftOwners/getNftTokenIdOwners/getWalletNfts/getWalletNftCollections) infer ownership from the latest confirmed nft_transfer per (chain, contract_address_id, token_id) and then aggregate by to_address_id; burned tokens are those whose last to_address_id is the zero/burn address, which must be represented as an addresses row per chain.
- NFT metadata endpoints (getNftMetadata/getContractNfts/getMultipleNfts/getNftBulkContractMetadata) read from assets where asset_type in ('nft_item','nft_collection') and match by (chain_id, contract_address_id, token_id) for items or (chain_id, contract_address_id) for collections; metadata JSON blob may be stale but must be served even if pricing fields are null.
- Floor price endpoints (getNftFloorPriceByContract/getNftHistoricalFloorPriceByContract) read assets.floor_price_* and floor_price_refreshed_at for latest; historical is derived from time-bucketed events rows stored as events.event_type='nft_trade' with metadata containing bucket timestamps and floor observations (or computed on read).
- Swap endpoints (getSwapsByTokenAddress/getSwapsByWalletAddress/getSwapsByPairAddress) read events.event_type='swap' filtered by asset_id/contract_address_id and relevant wallet address ids; include liquidity_add/liquidity_remove when requested by pair swap tool semantics.
- Pair analytics endpoints (getPairCandlesticks/getPairStats/getTokenPairs) read assets with asset_type='pair' and events with event_type in ('swap','liquidity_add','liquidity_remove'); candlesticks are computed by bucketing events.block_timestamp and aggregating price/volume from events.metadata fields.
- Discovery/search endpoints (searchTokens/getFilteredTokens/getTrendingTokensV2/getTopGainersTokens/getTopLosersTokens/getBlueChipTokens/etc.) filter assets where asset_type='erc20' (and optionally chain_id in a provided set) and sort by market_cap_usd/liquidity_usd/fdv_usd/latest_price_usd and derived changes; tools must not return assets where status='hidden' unless explicitly configured for internal use.
- Entity tools (searchEntities/getEntity/getEntityCategories/getEntitiesByCategory) read entities and entity_addresses joins; searchEntities must return grouped arrays for entities, addresses, and categories by combining entity name matching with addresses linked via entity_addresses, and categories from entities.category.
- Token owners/holders endpoints (getTokenOwners/getTokenHolders/getHistoricalTokenHolders/getTopProfitableWalletPerToken) compute holder sets from net confirmed token_transfer deltas per wallet; known labels/entities are added by joining addresses -> entity_addresses -> entities; time-series holders use block_timestamp bucketing over events.
- Numeric limits implied by tool descriptions must be enforced at query-layer: up to 25 NFTs for getMultipleNfts and getNftBulkContractMetadata, up to 100 tokens for getMultipleTokenPrices, and up to 200 tokens for getTimeseriesTokenAnalytics/getMultipleTokenAnalytics; requests exceeding limits must be rejected before querying.
- Only confirmed events (events.status='confirmed') are used for any financial/statistical output by default; pending may be shown only for verbose transaction tools when explicitly requested (not present in tool params, so default to confirmed).