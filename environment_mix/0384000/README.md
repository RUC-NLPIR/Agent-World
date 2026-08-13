# YNAB Budget Assistant — local MCP environment

This backend stores a local mirror of a user's YNAB budgets plus a lightweight sync cursor that allows incremental retrieval of unapproved transactions. Main workflows: discover budgets (list_budgets), show an aggregated snapshot for the active budget (budget_summary), create transactions (create_transaction), and poll for newly changed/unapproved transactions using a per-budget cursor (get_unapproved_transactions).

Repository: https://github.com/calebl/ynab-mcp-server
Homepage: https://smithery.ai/server/@calebl/ynab-mcp-server

## Datastore

- `ynab_connections.json` — Represents a configured connection to the YNAB API for a single user/installation of this assistant, including token metadata and default/active budget selection. (12 rows; fields: ['id', 'user_key', 'access_token_ciphertext', 'token_last4', 'active_budget_id', 'status', 'last_api_error', 'last_validated_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'error']
  - constraint: unique(user_key)
  - constraint: active_budget_id references budgets.id on delete set null
  - constraint: status in ('active','revoked','error')
- `budgets.json` — Local mirror of YNAB budgets available to a given connection, used for list_budgets and as the root entity for summaries and transaction operations. (12 rows; fields: ['id', 'connection_id', 'ynab_budget_id', 'name', 'currency_format', 'first_month', 'last_month', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'removed']
  - constraint: unique(connection_id, ynab_budget_id)
  - constraint: name <> ''
  - constraint: status in ('active','archived','removed')
  - constraint: connection_id references ynab_connections.id on delete cascade
- `transactions.json` — Local mirror of transactions for budgets, including approval state. Supports create_transaction and get_unapproved_transactions (read side), and provides summary aggregates. (36 rows; fields: ['id', 'budget_id', 'ynab_transaction_id', 'account_id', 'date', 'amount_milliunits', 'payee_id', 'payee_name', 'category_id', 'memo', 'cleared', 'approved', 'deleted', 'import_id', 'source', 'upstream_last_modified_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(budget_id, ynab_transaction_id)
  - constraint: approved in (true,false)
  - constraint: deleted in (true,false)
  - constraint: amount_milliunits between -900000000000 and 900000000000
- `sync_cursors.json` — Per-budget cursor/state used to implement 'first time pulls last 3 days, subsequent pulls use server knowledge to get only changes' for unapproved transactions and other incremental sync operations. (12 rows; fields: ['id', 'budget_id', 'cursor_type', 'since_date', 'server_knowledge', 'last_run_at', 'status', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ready', 'running', 'error']
  - constraint: unique(budget_id, cursor_type)
  - constraint: server_knowledge is null or server_knowledge >= 0
  - constraint: budget_id references budgets.id on delete cascade
  - constraint: cursor_type in ('unapproved_transactions')
- `budget_snapshots.json` — Cached summary materialization for budget_summary to avoid repeated full aggregation; can be refreshed on demand or periodically after sync/creates. (22 rows; fields: ['id', 'budget_id', 'as_of_at', 'unapproved_count', 'unapproved_outflow_milliunits', 'unapproved_inflow_milliunits', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['current', 'stale']
  - constraint: unique(budget_id, status) where status='current'
  - constraint: unapproved_count >= 0
  - constraint: budget_id references budgets.id on delete cascade

## Business rules enforced by the tools

- list_budgets returns budgets where budgets.connection_id matches the caller's ynab_connections.id and budgets.status != 'removed'; if no budgets exist locally or last_synced_at is stale, the service refreshes budgets from YNAB and upserts by (connection_id, ynab_budget_id).
- budget_summary operates against ynab_connections.active_budget_id; if active_budget_id is null, it must be set to the first active budget after list_budgets refresh, otherwise the tool fails with a deterministic error.
- budget_summary should prefer the single budget_snapshots row where (budget_id, status='current'); if missing or stale, it recomputes from transactions where budget_id matches, deleted=false, status='active', then upserts a new current snapshot and marks prior current snapshots as stale.
- create_transaction creates a transaction for the active budget; it must enforce that at least one of (payee_id, payee_name) is provided, date is provided, and amount_milliunits is non-zero unless explicitly allowed by upstream; it calls YNAB, then upserts into transactions with source='assistant_create' and ynab_transaction_id from the response.
- create_transaction must enforce de-duplication: if import_id is provided and a transaction with the same (budget_id, import_id) exists, the request is rejected or treated as idempotent according to implementation policy; if rejected, it must not call upstream.
- get_unapproved_transactions operates against the active budget and sync_cursors row for cursor_type='unapproved_transactions'. If the cursor does not exist, it is created with since_date = now() - interval '3 days' and server_knowledge = null.
- On the first get_unapproved_transactions run (server_knowledge is null), the service must query upstream from since_date and persist returned transactions into transactions (source='ynab_sync'), then set server_knowledge from upstream and last_run_at=now().
- On subsequent get_unapproved_transactions runs (server_knowledge not null), the service must request upstream deltas using server_knowledge, upsert changed transactions, and advance server_knowledge monotonically (never decreasing).
- get_unapproved_transactions returns only transactions where budget_id matches, approved=false, deleted=false, status='active'; it may additionally filter to those changed since last cursor run by using upstream_last_modified_at >= last_run_at when present.
- FK integrity: deleting a ynab_connections row cascades to budgets, which cascades to transactions, sync_cursors, and budget_snapshots; active_budget_id is set null if the referenced budget is removed.
- All write operations must update updated_at; any transition to ynab_connections.status='revoked' prevents further upstream calls and causes tools to fail with a permission/config error until reactivated.