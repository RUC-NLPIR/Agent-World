# Solana Token Creator — local MCP environment

This backend stores local key-managed Solana accounts, created Pump.fun tokens, and buy/sell trade intents with on-chain execution tracking. Primary workflows are: discover local accounts, check balances, create a token, and place buy/sell orders while persisting idempotency, statuses, and resulting transaction signatures.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@8bitsats/pump-mcp

## Datastore

- `accounts.json` — Locally managed Solana accounts discovered from the server's keys folder. Used for listing accounts, quoting balances, and as the signer/fee-payer for token creation and trades. (18 rows; fields: ['id', 'label', 'key_source', 'key_ref', 'public_key', 'status', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'missing_key', 'compromised']
  - constraint: unique(public_key)
  - constraint: unique(label) where label is not null
  - constraint: public_key matches base58 format and length between 32 and 44 chars
  - constraint: key_ref is required and non-empty
- `tokens.json` — Pump.fun tokens created/known by the service, with mint address, optional metadata, and creation transaction tracking. (18 rows; fields: ['id', 'mint_address', 'pump_market_address', 'creator_account_id', 'name', 'symbol', 'decimals', 'metadata_uri', 'status', 'create_request_id', 'create_tx_signature', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'creating', 'live', 'failed', 'archived']
  - constraint: unique(mint_address)
  - constraint: unique(create_request_id) where create_request_id is not null
  - constraint: mint_address matches base58 format and length between 32 and 44 chars
  - constraint: decimals is null or (decimals >= 0 and decimals <= 18)
- `account_balances.json` — Cached balances per account for SOL and tokens. Updated via RPC reads when get-account-balance is called. (18 rows; fields: ['id', 'account_id', 'asset_type', 'mint_address', 'amount_raw', 'decimals', 'slot', 'refreshed_at', 'created_at', 'updated_at'])
  - lifecycle `asset_type`: ['SOL', 'SPL']
  - constraint: unique(account_id, asset_type, mint_address)
  - constraint: asset_type='SOL' implies mint_address is null and decimals is null
  - constraint: asset_type='SPL' implies mint_address is not null
  - constraint: amount_raw matches regex ^[0-9]+$
- `trades.json` — Buy/sell requests against Pump.fun tokens, including requested sizing, execution status, and resulting on-chain transaction signature(s). (18 rows; fields: ['id', 'side', 'account_id', 'token_id', 'request_id', 'requested_input_mint', 'requested_output_mint', 'amount_in_raw', 'amount_out_raw', 'slippage_bps', 'status', 'failure_reason', 'tx_signature', 'confirmed_slot', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'building', 'submitted', 'confirmed', 'failed', 'cancelled']
  - constraint: unique(request_id) where request_id is not null
  - constraint: account_id references accounts(id) on delete restrict
  - constraint: token_id references tokens(id) on delete restrict
  - constraint: slippage_bps is null or (slippage_bps >= 0 and slippage_bps <= 10000)
- `rpc_requests.json` — Audit/telemetry of Solana RPC calls triggered by tools (balance fetches, token info lookups, tx submit/confirm). Supports debugging, rate limiting, and correlating tool actions to chain reads/writes. (18 rows; fields: ['id', 'tool_name', 'account_id', 'token_id', 'trade_id', 'rpc_method', 'rpc_params', 'http_status', 'rpc_error', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `http_status`: []
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: http_status is null or (http_status >= 100 and http_status <= 599)
  - constraint: account_id references accounts(id) on delete set null
  - constraint: token_id references tokens(id) on delete set null

## Business rules enforced by the tools

- list-accounts returns accounts where key_source='keys_folder' and status != 'compromised'; if a key file is missing on disk, the service must set status='missing_key' and last_seen_at to now.
- get-account-balance must upsert account_balances for the requested account_id for SOL and any discovered SPL token accounts; refreshed_at must be updated on every successful fetch.
- create-token must create a tokens row in status='creating' tied to creator_account_id, then set create_tx_signature and transition to 'live' only after confirmation; on failure it must transition to 'failed' with an RPC error recorded in rpc_requests.
- get-token-info must be able to resolve a token by mint_address (tokens.mint_address) or by known token_id; if the mint is unknown locally, the service may create a tokens row with status='live' and null metadata after fetching from chain.
- buy-token and sell-token must create a trades row with status='queued' and side in ('buy','sell'); the trade may only transition forward according to trades.lifecycle.transitions and must store tx_signature once submitted.
- For buy-token, amount_in_raw must be provided or inferred from configured defaults; for sell-token, amount_out_raw must be provided or inferred; the service must reject requests that would result in a zero-amount trade.
- A trade cannot be submitted if accounts.status != 'active' or tokens.status not in ('live'); such requests must be rejected or recorded as failed with failure_reason.
- Idempotency: if request_id is provided on create-token or trades, repeated calls with the same request_id must return the existing tokens/trades row and must not create a new on-chain transaction.
- Any RPC call initiated by a tool must create an rpc_requests row; rpc_params must be sanitized to exclude secret keys, seed phrases, or raw key bytes.
- Uniqueness and FK integrity must be enforced: tokens.mint_address unique; account_balances unique(account_id, asset_type, mint_address); trades must reference existing accounts and tokens.