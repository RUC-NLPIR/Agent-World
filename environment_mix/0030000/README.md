# Blockscout MCP Server — local MCP environment

This backend powers an MCP server that brokers read-only blockchain explorer queries to Blockscout across many chains, while enforcing per-session initialization and capturing request/response telemetry for pagination, caching and troubleshooting. Core workflows are: client starts a session and calls __get_instructions__, then performs chain-scoped reads (blocks, transactions, addresses, tokens, NFTs, logs) with optional cursors and time filters, with results optionally served from cache.

Repository: https://github.com/blockscout/mcp-server
Homepage: https://smithery.ai/server/@blockscout/mcp-server

## Datastore

- `mcp_sessions.json` — Represents an MCP client session. Enforces that __get_instructions__ is called once before other tools and tracks lifecycle for auditing and rate limiting. (31 rows; fields: ['id', 'status', 'instructions_called_at', 'client_name', 'client_version', 'transport_metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['new', 'initialized', 'closed', 'expired']
  - constraint: instructions_called_at IS NULL when status='new'
  - constraint: instructions_called_at IS NOT NULL when status IN ('initialized','closed','expired')
  - constraint: updated_at >= created_at
- `chains.json` — Known Blockscout-supported chains. Used to validate chain_id for all chain-scoped tools and to route requests to the correct upstream API base URL. (30 rows; fields: ['id', 'chain_id', 'name', 'short_name', 'blockscout_api_base_url', 'blockscout_explorer_base_url', 'status', 'last_indexed_block_number', 'last_indexed_block_timestamp', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'degraded', 'disabled']
  - constraint: unique(chain_id)
  - constraint: unique(blockscout_api_base_url)
  - constraint: last_indexed_block_number IS NULL OR last_indexed_block_number >= 0
- `tool_requests.json` — Append-only log of each MCP tool invocation with normalized parameters for filtering, enforcement (must call __get_instructions__ first), and debugging. Also stores pagination cursors and time filters used by list tools. (32 rows; fields: ['id', 'session_id', 'tool_name', 'chain_id', 'address', 'transaction_hash', 'number_or_hash', 'ens_name', 'symbol_query', 'token_address', 'age_from', 'age_to', 'methods', 'include_transactions', 'include_raw_input', 'cursor', 'status', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'validated', 'served_from_cache', 'upstream_fetching', 'succeeded', 'failed', 'rejected']
  - constraint: FK(session_id) references mcp_sessions(id) on delete cascade
  - constraint: If tool_name IN ('get_block_info','get_latest_block','get_transactions_by_address','get_token_transfers_by_address','lookup_token_by_symbol','get_contract_abi','get_address_info','get_tokens_by_address','transaction_summary','nft_tokens_by_address','get_transaction_info','get_transaction_logs','get_address_logs') then chain_id IS NOT NULL
  - constraint: If tool_name='get_block_info' then number_or_hash IS NOT NULL
  - constraint: If tool_name IN ('get_transactions_by_address','get_token_transfers_by_address','get_address_info','get_tokens_by_address','nft_tokens_by_address','get_address_logs') then address IS NOT NULL
- `response_cache.json` — Cached upstream responses keyed by normalized tool+parameters to reduce upstream load and speed repeated reads. Stores cursored pages as separate cache entries. (38 rows; fields: ['id', 'cache_key', 'tool_name', 'chain_id', 'normalized_params', 'payload', 'payload_bytes', 'etag', 'expires_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'purged']
  - constraint: unique(cache_key)
  - constraint: payload_bytes >= 0
  - constraint: expires_at > created_at
  - constraint: If status='fresh' then expires_at > NOW() (enforced at write time)
- `upstream_calls.json` — Tracks the actual HTTP calls made to Blockscout or related services (e.g., Transaction Interpreter). Allows debugging latency, failures, and mapping tool_requests to concrete upstream endpoints. (35 rows; fields: ['id', 'tool_request_id', 'chain_id', 'upstream_service', 'http_method', 'url', 'request_headers', 'request_body', 'response_status_code', 'response_body_preview', 'duration_ms', 'status', 'error_class', 'created_at', 'updated_at'])
  - lifecycle `status`: ['started', 'succeeded', 'failed', 'timed_out']
  - constraint: FK(tool_request_id) references tool_requests(id) on delete cascade
  - constraint: duration_ms >= 0
  - constraint: response_status_code IS NULL OR (response_status_code >= 100 AND response_status_code <= 599)

## Business rules enforced by the tools

- A session MUST call __get_instructions__ exactly once: for any mcp_sessions row, status can transition from 'new' to 'initialized' only via a recorded tool_requests row with tool_name='__get_instructions__' and status='succeeded'.
- Any tool request other than __get_instructions__ MUST be rejected (tool_requests.status='rejected', error_code='NOT_INITIALIZED') if the referenced session status is 'new'.
- For get_chains_list, chain_id MUST be NULL; for all other chain-scoped tools, chain_id MUST exist in chains with chains.status != 'disabled' or the request is rejected with error_code='INVALID_CHAIN' or 'CHAIN_DISABLED'.
- Addresses stored in tool_requests.address and token_address MUST be normalized to lowercase hex with 0x prefix; invalid formats are rejected with error_code='INVALID_ADDRESS'.
- Transaction hashes stored in tool_requests.transaction_hash MUST be normalized to lowercase 0x-prefixed 32-byte hex; invalid formats are rejected with error_code='INVALID_TX_HASH'.
- For time-windowed tools (get_transactions_by_address, get_token_transfers_by_address), if both age_from and age_to are provided then age_from <= age_to; otherwise reject with error_code='INVALID_TIME_RANGE'.
- For get_token_transfers_by_address, if age_from is NULL the server SHOULD enforce a safety limit (e.g., reject or force a capped lookback) to avoid heavy queries; recorded as tool_requests.status='rejected' with error_code='MISSING_AGE_FROM' when policy is strict.
- Cursor parameters are only valid for (get_tokens_by_address, nft_tokens_by_address, get_transaction_logs, get_address_logs); providing cursor to other tools is rejected with error_code='UNEXPECTED_CURSOR'.
- response_cache.cache_key MUST be computed from (tool_name, chain_id, normalized_params) and be unique; cache writes update existing rows only by transitioning status and overwriting payload/expiry atomically.
- A tool request can be marked served_from_cache only if a response_cache row exists with matching cache_key, status='fresh', and expires_at > now().
- Each tool_requests row that reaches status 'upstream_fetching' MUST have at least one upstream_calls row created with status='started'; completion MUST transition to succeeded/failed/timed_out and set duration_ms.
- chains.last_indexed_block_number and last_indexed_block_timestamp can only move forward (monotonic) when refreshed from upstream; attempts to regress are ignored or rejected.