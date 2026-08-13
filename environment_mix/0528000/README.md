# Etherscan Tools — local MCP environment

This backend persists cached Ethereum on-chain lookups and Etherscan-derived metadata (balances, transactions, token transfers, contract ABIs/source, gas prices, ENS reverse records) keyed by chain and address/contract. The main workflow is: a client calls a tool, the service checks cached entities, optionally refreshes via Etherscan, records the request/response for auditing and rate limiting, and serves the latest successful snapshot.

Repository: https://github.com/ThirdGuard/mcp-etherscan-server
Homepage: https://smithery.ai/server/@ThirdGuard/mcp-etherscan-server

## Datastore

- `api_keys.json` — API keys for clients of this MCP service (distinct from the upstream Etherscan key). Used for authentication, quota enforcement, and auditing requests. (32 rows; fields: ['id', 'key_hash', 'label', 'status', 'rate_limit_per_minute', 'daily_quota', 'allowed_chain_ids', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: rate_limit_per_minute between 1 and 6000
  - constraint: daily_quota between 1 and 10000000
  - constraint: allowed_chain_ids length >= 1
- `requests.json` — Audit log of tool invocations and their upstream/cache outcomes. Powers metering, debugging, and replay of recent responses. (36 rows; fields: ['id', 'api_key_id', 'tool_name', 'chain_id', 'subject_address', 'contract_address', 'cache_hit', 'upstream_provider', 'upstream_http_status', 'status', 'error_code', 'error_message', 'response_ref', 'latency_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'served', 'failed', 'rate_limited']
  - constraint: foreign key (api_key_id) references api_keys(id) on delete restrict
  - constraint: chain_id in (1,5,11155111,137,10,42161,56) OR supported chains configured
  - constraint: subject_address matches /^0x[0-9a-fA-F]{40}$/ when not null
  - constraint: contract_address matches /^0x[0-9a-fA-F]{40}$/ when not null
- `address_state.json` — Latest known state for an Ethereum address per chain: balance snapshot, ENS reverse name, and last synced block heights for tx and token transfer history. (30 rows; fields: ['id', 'chain_id', 'address', 'balance_wei', 'balance_as_of_block', 'ens_name', 'ens_checked_at', 'tx_synced_through_block', 'token_transfers_synced_through_block', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'blocked']
  - constraint: unique(chain_id, address)
  - constraint: address matches /^0x[0-9a-f]{40}$/ (normalized lowercase)
  - constraint: balance_as_of_block >= 0 when not null
  - constraint: tx_synced_through_block >= 0 when not null
- `transactions.json` — Indexed transaction list items for addresses (normal transactions). Used to serve get-transactions quickly without hitting upstream for recent history. (34 rows; fields: ['id', 'chain_id', 'address_state_id', 'tx_hash', 'block_number', 'tx_index', 'from_address', 'to_address', 'value_wei', 'gas_used', 'gas_price_wei', 'timestamp', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['confirmed', 'reorged', 'pending', 'failed_parse']
  - constraint: foreign key (address_state_id) references address_state(id) on delete cascade
  - constraint: unique(chain_id, address_state_id, tx_hash)
  - constraint: tx_hash matches /^0x[0-9a-fA-F]{64}$/
  - constraint: from_address matches /^0x[0-9a-f]{40}$/
- `token_transfers.json` — ERC20 token transfer events indexed for addresses. Used to serve get-token-transfers. (34 rows; fields: ['id', 'chain_id', 'address_state_id', 'tx_hash', 'log_index', 'block_number', 'token_contract', 'from_address', 'to_address', 'amount_raw', 'token_symbol', 'token_decimals', 'timestamp', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['confirmed', 'reorged', 'failed_parse']
  - constraint: foreign key (address_state_id) references address_state(id) on delete cascade
  - constraint: unique(chain_id, address_state_id, tx_hash, log_index)
  - constraint: tx_hash matches /^0x[0-9a-fA-F]{64}$/
  - constraint: log_index >= 0
- `contract_metadata.json` — Verified contract metadata cached from Etherscan: ABI and source code blobs per contract address and chain. Used to serve get-contract-abi and get-contract-code. (32 rows; fields: ['id', 'chain_id', 'contract_address', 'contract_name', 'abi_json', 'source_code', 'compiler_version', 'optimization_enabled', 'runs', 'license_type', 'verified', 'last_fetched_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'missing', 'blocked']
  - constraint: unique(chain_id, contract_address)
  - constraint: contract_address matches /^0x[0-9a-f]{40}$/ (normalized lowercase)
  - constraint: runs >= 0 when not null
  - constraint: if verified = false then abi_json may be null and source_code may be null

## Business rules enforced by the tools

- Every tool invocation must create exactly one requests row with tool_name set to the called tool and status transitioned from received -> (served|failed|rate_limited).
- Requests must be rejected (recorded as rate_limited) when the calling api_key.status != 'active', when the per-minute rate limit is exceeded, or when daily_quota is exceeded.
- For check-balance and get-ens-name, the service must read/write address_state by (chain_id, address); if no row exists, it must be created with status='active' before storing results.
- For get-transactions, results must be served from transactions filtered by address_state_id (and ordered by block_number desc, tx_index desc when present); on cache miss/stale, the service refreshes from upstream and upserts transactions enforcing unique(chain_id,address_state_id,tx_hash).
- For get-token-transfers, results must be served from token_transfers filtered by address_state_id (ordered by block_number desc, log_index desc); refresh must upsert enforcing unique(chain_id,address_state_id,tx_hash,log_index).
- For get-contract-abi and get-contract-code, the service must read/write contract_metadata by (chain_id, contract_address); if status in ('stale','missing') or last_fetched_at older than TTL, refresh from upstream and update last_fetched_at and status accordingly.
- For get-gas-prices, the service may call upstream without a dedicated table; however each call must still be recorded in requests with subject_address and contract_address null and upstream_provider either 'etherscan' or 'none' (if served from an in-memory cache).
- All addresses stored in address_state, transactions, token_transfers, and contract_metadata must be normalized lowercase and validated to 20-byte hex; tx hashes must be 32-byte hex.
- FK integrity: deleting an address_state row must cascade delete its transactions and token_transfers; api_keys cannot be deleted while requests reference them (restrict).