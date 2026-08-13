# Monday.com MCP - Typescript — local MCP environment

This backend models a Monday.com integration layer that caches account structure (workspaces, boards) and board content (items) while tracking bulk item creation workflows. It supports read tools for listing/fetching workspaces/boards/items and write tools for creating/deleting items, including a two-phase "show example then create remaining" bulk creation flow with optional demo column data.

Repository: https://github.com/launchthatbrand/mcp-monday-ts
Homepage: https://smithery.ai/server/@launchthatbrand/mcp-monday-ts

## Datastore

- `monday_accounts.json` — Represents a connected Monday.com account/tenant for which we cache entities and execute mutations. In production this would be keyed by a connected integration installation and store auth/connection status. (12 rows; fields: ['id', 'monday_account_id', 'name', 'api_base_url', 'auth_type', 'api_token_ciphertext', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(monday_account_id)
  - constraint: api_base_url must be a valid URL
  - constraint: status in ('active','disabled','revoked')
  - constraint: api_token_ciphertext is required when status != 'revoked'
- `workspaces.json` — Cached Monday.com workspaces for an account. Used by get_workspaces and get_workspace and as parent for boards. (12 rows; fields: ['id', 'account_id', 'monday_workspace_id', 'name', 'kind', 'status', 'remote_updated_at', 'synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(account_id, monday_workspace_id)
  - constraint: status in ('active','archived')
  - constraint: fk(workspaces.account_id) references monday_accounts.id
- `boards.json` — Cached Monday.com boards, optionally scoped to a workspace. Supports list_boards, get_boards (by workspace), and get_board. (34 rows; fields: ['id', 'account_id', 'workspace_id', 'monday_board_id', 'name', 'description', 'board_kind', 'permissions', 'status', 'remote_updated_at', 'synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(account_id, monday_board_id)
  - constraint: fk(boards.account_id) references monday_accounts.id
  - constraint: fk(boards.workspace_id) references workspaces.id (nullable)
  - constraint: status in ('active','archived','deleted')
- `items.json` — Cached Monday.com items (rows) that live on a board. Supports get_items, get_item, create_item, delete_item, and is populated/updated by bulk creation tools. (37 rows; fields: ['id', 'account_id', 'board_id', 'monday_item_id', 'name', 'group_id', 'column_values', 'created_by', 'status', 'remote_created_at', 'remote_updated_at', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['pending_create', 'active', 'create_failed', 'deleted']
  - constraint: fk(items.account_id) references monday_accounts.id
  - constraint: fk(items.board_id) references boards.id
  - constraint: unique(account_id, monday_item_id) where monday_item_id is not null
  - constraint: name length between 1 and 255
- `bulk_item_jobs.json` — Tracks multi-step creation flows used by create_item_with_demo, create_multiple_items (show example first), and create_remaining_items (finish the batch). Stores templates/demo settings and progress for idempotency and retries. (12 rows; fields: ['id', 'account_id', 'board_id', 'status', 'requested_total', 'created_count', 'example_item_id', 'demo_mode', 'demo_column_ids', 'item_name_prefix', 'template_column_values', 'idempotency_key', 'error_message', 'started_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'example_created', 'running', 'completed', 'failed', 'cancelled']
  - constraint: fk(bulk_item_jobs.account_id) references monday_accounts.id
  - constraint: fk(bulk_item_jobs.board_id) references boards.id
  - constraint: fk(bulk_item_jobs.example_item_id) references items.id (nullable)
  - constraint: requested_total between 1 and 5000

## Business rules enforced by the tools

- All tools operate within exactly one monday_accounts row resolved from runtime configuration; mutations must be rejected when monday_accounts.status != 'active'.
- list_boards returns boards where account_id matches and status != 'deleted'.
- get_boards filters boards by workspace_id and account_id; if workspace_id not found for that account, return empty (do not leak other account data).
- get_board requires a board identifier resolvable to (account_id, monday_board_id) or internal boards.id; returned board must belong to the active account.
- get_workspaces returns workspaces for the account where status='active' (or includes archived only if explicitly configured server-side).
- get_workspace requires a workspace identifier resolvable to (account_id, monday_workspace_id) or internal workspaces.id and must belong to the account.
- get_items returns items for the specified board where status in ('active','pending_create','create_failed') and deleted_at is null.
- get_item requires an identifier resolvable to (account_id, monday_item_id) or internal items.id; must belong to the account and not be status='deleted'.
- create_item inserts an items row with status='pending_create', then on successful Monday API creation sets monday_item_id, status='active', remote_created_at, remote_updated_at; on failure sets status='create_failed' and preserves error in server logs (optional).
- delete_item is a soft delete in this backend: set items.status='deleted' and deleted_at=now; if Monday remote delete succeeds, also clear/retain monday_item_id per retention policy but never reuse it.
- create_item_with_demo creates exactly one item on a board; if demo_mode is enabled, demo values are generated only for allowed columns and stored in items.column_values; created item ends in status='active' or 'create_failed'.
- create_multiple_items creates a bulk_item_jobs row in status='draft' (or reuses existing by idempotency_key), creates the example item, sets bulk_item_jobs.status='example_created' and bulk_item_jobs.example_item_id to the created items.id, and sets created_count=1 on success.
- create_remaining_items requires an existing bulk_item_jobs in status in ('example_created','running'); it transitions to 'running', creates remaining items up to requested_total, updates created_count atomically, and ends in 'completed' when created_count=requested_total; failures set status='failed' with error_message and are retryable only by transitioning failed->draft.
- FK integrity: items.board_id must reference a boards row with same account_id; boards.workspace_id if set must reference a workspaces row with same account_id.
- Uniqueness: monday_workspace_id and monday_board_id are unique per account; monday_item_id is unique per account when present.
- Status transitions must follow each collection.lifecycle.transitions; invalid transitions are rejected at the database or service layer.