# Coin MCP Server — local MCP environment

This backend powers a cryptocurrency info/search MCP service by storing a catalog of tokens, their current price snapshots, and exchange-style announcements. It supports read-only tools to fetch latest token price, query announcements within the last month by type, and fetch coin transfer/chain (deposit/withdraw) metadata.

Repository: https://github.com/pwh-pwh/coin-mcp-server
Homepage: https://smithery.ai/server/@pwh-pwh/coin-mcp-server

## Datastore

- `tokens.json` — Canonical token/coin registry used to normalize user inputs (symbol/name) and link to prices and chain support metadata. (18 rows; fields: ['id', 'symbol', 'name', 'aliases', 'is_spot_supported', 'transfer', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'delisted']
  - constraint: unique(lower(symbol))
  - constraint: aliases is array of unique lowercased strings
  - constraint: status in ('active','inactive','delisted')
  - constraint: is_spot_supported implies status != 'inactive' is NOT required (allowed), but delisted coins should not be is_spot_supported=true
- `token_chain_support.json` — Per-token supported chain list with deposit/withdraw/tag requirements and fees. Serves the 'chains' section of getCoinInfo. (18 rows; fields: ['id', 'token_id', 'chain', 'needTag', 'withdrawable', 'rechargeable', 'withdrawFee', 'extraWithdrawFee', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['enabled', 'disabled']
  - constraint: foreign key(token_id) references tokens(id) on delete cascade
  - constraint: unique(token_id, lower(chain))
  - constraint: withdrawFee >= 0
  - constraint: extraWithdrawFee >= 0 and extraWithdrawFee <= 1
- `token_price_snapshots.json` — Time-series snapshots of token prices used to answer getTokenPrice with the freshest datapoint for a token. (18 rows; fields: ['id', 'token_id', 'quote_currency', 'price', 'source', 'as_of', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['valid', 'stale', 'invalid']
  - constraint: foreign key(token_id) references tokens(id) on delete cascade
  - constraint: price > 0
  - constraint: quote_currency in ('USD','USDT')
  - constraint: as_of <= created_at
- `announcements.json` — Announcement feed items, filterable by type and time window (last month) for getAnnoucements. (18 rows; fields: ['id', 'anType', 'title', 'body', 'url', 'published_at', 'source', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['published', 'retracted', 'archived']
  - constraint: anType in ('latest_news','coin_listings','trading_competitions_promotions','maintenance_system_updates','symbol_delisting')
  - constraint: published_at <= created_at
  - constraint: created_at <= updated_at
  - constraint: index(anType, published_at desc) to support type+time queries
- `api_request_logs.json` — Operational logging of tool calls for rate limiting, debugging and analytics. Not directly exposed by tools but required for a production API service. (18 rows; fields: ['id', 'tool_name', 'request_params', 'resolved_token_id', 'response_status_code', 'latency_ms', 'error_code', 'created_at', 'updated_at'])
  - constraint: tool_name in ('getTokenPrice','getAnnoucements','getCoinInfo')
  - constraint: response_status_code between 100 and 599
  - constraint: latency_ms >= 0 and latency_ms <= 300000
  - constraint: foreign key(resolved_token_id) references tokens(id) on delete set null

## Business rules enforced by the tools

- getTokenPrice(token): token input is normalized by trimming and uppercasing, then matched against tokens.symbol or tokens.aliases (case-insensitive). If no match, return an error and log error_code='TOKEN_NOT_FOUND'.
- getTokenPrice returns the most recent token_price_snapshots row for the resolved token_id where status='valid' and quote_currency in ('USDT','USD'); if the newest snapshot is older than a configured staleness threshold (e.g., 5 minutes), it may be returned but must be marked stale at the application layer and the snapshot status transitioned valid->stale asynchronously.
- getAnnoucements(anType): if anType is empty string, return all announcements; otherwise filter announcements.anType = anType. Always restrict results to published_at >= now() - interval '1 month' and status='published'.
- getCoinInfo(coin): coin input is normalized and resolved to tokens via symbol or aliases; response returns tokens.symbol as 'coin', tokens.transfer as 'transfer', and chains from token_chain_support where status='enabled', ordered by chain.
- token_chain_support rows must not exist for tokens.status='delisted' unless status='disabled' (enforced by application validation on write).
- Announcement items must have published_at within a reasonable bound (not more than 24h in the future relative to ingestion) or be rejected as invalid upstream data.
- All tool invocations must create an api_request_logs record with tool_name, request_params, response_status_code and latency_ms.