# COTI Blockchain MCP Server — local MCP environment

This backend stores locally-managed COTI accounts (addresses plus encrypted private/AES keys), tracks which account is the current default, and records blockchain interactions initiated through the MCP tools. It also persists deployed token/NFT contract metadata and keeps an audit trail of submitted transactions plus decoded logs and read-call results to support status checks, log retrieval, and repeatable reads.

Repository: https://github.com/davibauer/coti-mcp
Homepage: https://smithery.ai/server/@davibauer/coti-mcp

## Datastore

- `accounts.json` — Locally managed COTI accounts/wallets. Stores address plus encrypted private key material and per-account AES key used for COTI privacy operations. Used by create_account, list_accounts, change_default_account, generate_aes_key, sign_message, encrypt/decrypt_value, and as the "from" identity for transfers/approvals/mints. (18 rows; fields: ['id', 'address', 'label', 'private_key_encrypted', 'aes_key_encrypted', 'key_version', 'is_default', 'status', 'archived_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(lower(address))
  - constraint: key_version >= 1
  - constraint: is_default implies status='active'
  - constraint: at_most_one_row_where(is_default=true)
- `contracts.json` — Smart contract metadata for contracts deployed/used through the MCP server, including private ERC20 and private ERC721. Supports deploy_private_erc20_contract, deploy_private_erc721_contract, and provides cached attributes for read tools (decimals/totalSupply/name/symbol). (18 rows; fields: ['id', 'chain_id', 'address', 'contract_type', 'name', 'symbol', 'decimals', 'abi_json', 'deployed_by_account_id', 'deployment_tx_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated']
  - constraint: unique(chain_id, lower(address))
  - constraint: address must match '^0x[0-9a-fA-F]{40}$'
  - constraint: if contract_type='private_erc20' then decimals is null or (decimals between 0 and 255)
- `transactions.json` — Outbound on-chain transactions initiated by tools (native transfers, approvals, mints, transfers, deployments) plus their observed status from the chain. Also used as the anchor for transaction logs. Powers get_transaction_status and get_transaction_logs. (20 rows; fields: ['id', 'chain_id', 'tx_hash', 'initiator_account_id', 'tool_name', 'tx_type', 'to_address', 'contract_id', 'value_wei', 'function_selector', 'call_data_hex', 'inputs_json', 'submitted_at', 'mined_at', 'block_number', 'status', 'failure_reason', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'confirmed', 'failed', 'dropped']
  - constraint: unique(chain_id, lower(tx_hash))
  - constraint: tx_hash must match '^0x[0-9a-fA-F]{64}$'
  - constraint: to_address is null or matches '^0x[0-9a-fA-F]{40}$'
  - constraint: value_wei is null or (value_wei as decimal string) >= 0
- `transaction_logs.json` — Event logs for a given transaction hash, optionally decoded using known ABIs/event signatures. Serves get_transaction_logs and supports decode_event_data caching. (20 rows; fields: ['id', 'transaction_id', 'log_index', 'emitter_address', 'topics', 'data', 'event_signature', 'event_name', 'decoded_args_json', 'decode_status', 'created_at', 'updated_at'])
  - lifecycle `decode_status`: ['raw', 'decoded', 'decode_failed']
  - constraint: unique(transaction_id, log_index)
  - constraint: log_index >= 0
  - constraint: emitter_address must match '^0x[0-9a-fA-F]{40}$'
  - constraint: every topics[i] must match '^0x[0-9a-fA-F]{64}$' or '^0x[0-9a-fA-F]{0,64}$' (clients vary in padding)
- `crypto_operations.json` — Audit trail of off-chain cryptographic operations performed by the server: encrypt_value, decrypt_value, sign_message, verify_signature, and decode_event_data/call_contract_function results. Stores inputs/outputs (redacted where necessary) and ties operations to a local account when applicable. (19 rows; fields: ['id', 'op_type', 'account_id', 'contract_address', 'function_selector', 'function_name', 'inputs_json', 'result_json', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'failed']
  - constraint: if op_type in ('encrypt_value','decrypt_value','sign_message') then account_id is not null
  - constraint: if op_type='encrypt_value' then contract_address is not null and function_selector is not null
  - constraint: contract_address is null or matches '^0x[0-9a-fA-F]{40}$'
  - constraint: function_selector is null or matches '^0x[0-9a-fA-F]{8}$'

## Business rules enforced by the tools

- change_default_account must set exactly one accounts.is_default=true among accounts with status='active'; all other accounts must have is_default=false.
- create_account must generate a new unique address; inserting an address that already exists (case-insensitive) must fail.
- list_accounts must never return private_key_encrypted/aes_key_encrypted in plaintext; it may return masked versions derived at read-time.
- export_accounts must serialize only accounts with status='active' and include sufficient encrypted key material plus key_version to restore accounts via import_accounts without loss.
- import_accounts must be idempotent by address: if an imported address already exists, it must either (a) be rejected, or (b) update encrypted key material only when key_version is higher; it must never silently overwrite with an older key_version.
- generate_aes_key must rotate the AES key for the current default account by updating aes_key_encrypted and incrementing key_version; previous aes_key_encrypted must not be retrievable via list/export unless explicitly retained and encrypted in a separate vault (not modeled here).
- encrypt_value must record a crypto_operations row with op_type='encrypt_value' tied to the account that performed encryption; it must validate contract_address and function_selector formats.
- decrypt_value must only be permitted when the referenced account has a non-null aes_key_encrypted; otherwise it must fail and write crypto_operations.status='failed'.
- sign_message must create a crypto_operations row; verify_signature must create a crypto_operations row with recovered address in result_json.
- All on-chain mutating tools (transfer_native, approvals, mints, transfers, deployments) must create a transactions row with status='pending' at submission time and must enforce tx_hash uniqueness per chain_id.
- get_transaction_status must resolve by tx_hash; if a transactions row exists it should be refreshed from the chain and status transitioned only according to transactions.lifecycle.transitions.
- get_transaction_logs must resolve by tx_hash; it must upsert transaction_logs for each (transaction_id, log_index) and never create duplicates.
- decode_event_data must either (a) return a decoded structure and write crypto_operations.status='succeeded', or (b) fail with status='failed'; if tied to a stored transaction log, it should update transaction_logs.decode_status accordingly.
- deploy_private_erc20_contract and deploy_private_erc721_contract must create (1) a pending transactions row of tx_type='deploy_contract' and (2) upon confirmation, an active contracts row with unique (chain_id, address).
- ERC20/ERC721 approval and transfer tools must validate all provided addresses are 0x-prefixed 20-byte hex and numeric inputs (amount, tokenId) are non-negative; invalid inputs must not create confirmed transactions rows.
- value_wei for transfer_native must be a non-negative integer encoded as a base-10 string; zero-value transfers are allowed but must still produce a transaction record.