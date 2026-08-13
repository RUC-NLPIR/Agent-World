# YNAB Server — local MCP environment

This backend stores a local, queryable mirror of a user’s YNAB data (budgets, accounts, payees, categories, months, and transactions) so the MCP tools can answer reads quickly and consistently. The main workflows are: authenticate/link a YNAB user, sync one or more budgets from YNAB into local collections, and serve read/search/summary endpoints over the mirrored data with lightweight caching and auditability.

Repository: https://github.com/ChuckBryan/ynabmcpserver
Homepage: https://smithery.ai/server/@ChuckBryan/ynabmcpserver

## Datastore

- `users.json` — Represents a linked YNAB user identity and the server-side integration state used to fetch and cache data from YNAB for the MCP tools. (12 rows; fields: ['id', 'ynab_user_id', 'display_name', 'status', 'ynab_access_token_ciphertext', 'token_last_verified_at', 'last_full_sync_at', 'last_error_code', 'last_error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'error']
  - constraint: unique(ynab_user_id) where ynab_user_id is not null
  - constraint: ynab_access_token_ciphertext is required when status in ('active','error')
  - constraint: token_last_verified_at <= updated_at when token_last_verified_at is not null
- `budgets.json` — YNAB budgets mirrored locally for a given linked user; used by ListBudgets and as the root for accounts/categories/months/transactions. (20 rows; fields: ['id', 'user_id', 'ynab_budget_id', 'name', 'currency_format', 'first_month', 'last_modified_on', 'status', 'last_sync_at', 'last_sync_cursor', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'syncing', 'sync_error']
  - constraint: foreign key(user_id) references users(id) on delete cascade
  - constraint: unique(user_id, ynab_budget_id)
  - constraint: name <> ''
  - constraint: last_modified_on is null or last_modified_on <= updated_at
- `accounts.json` — Accounts within a budget, used by ListAccounts and to scope ListAccountTransactions. (36 rows; fields: ['id', 'budget_id', 'ynab_account_id', 'name', 'type', 'on_budget', 'closed', 'balance_milliunits', 'cleared_balance_milliunits', 'uncleared_balance_milliunits', 'status', 'last_modified_on', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'closed', 'syncing', 'sync_error']
  - constraint: foreign key(budget_id) references budgets(id) on delete cascade
  - constraint: unique(budget_id, ynab_account_id)
  - constraint: name <> ''
- `budget_entities.json` — Budget-scoped non-transaction entities (payees, categories, months) mirrored from YNAB. This denormalizes three related resource types into one table to stay within the collection limit while still mapping cleanly to the tool surface. (33 rows; fields: ['id', 'budget_id', 'entity_type', 'ynab_entity_id', 'name', 'parent_ynab_entity_id', 'hidden', 'month', 'note', 'budgeted_milliunits', 'activity_milliunits', 'to_be_budgeted_milliunits', 'status', 'last_modified_on', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'syncing', 'sync_error']
  - constraint: foreign key(budget_id) references budgets(id) on delete cascade
  - constraint: unique(budget_id, entity_type, ynab_entity_id)
  - constraint: entity_type='month' implies month is not null
  - constraint: entity_type in ('payee','category') implies (name is not null and name <> '')
- `transactions.json` — Transactions mirrored from YNAB. Supports list-by-account and full-text-like search by memo/payee as required by ListAccountTransactions and SearchTransactions, and powers summary tools. (40 rows; fields: ['id', 'budget_id', 'account_id', 'ynab_transaction_id', 'date', 'amount_milliunits', 'payee_entity_id', 'category_entity_id', 'memo', 'cleared', 'approved', 'flag_color', 'transfer_account_id', 'import_id', 'deleted', 'status', 'last_modified_on', 'search_text', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'syncing', 'sync_error']
  - constraint: foreign key(budget_id) references budgets(id) on delete cascade
  - constraint: foreign key(account_id) references accounts(id) on delete cascade
  - constraint: unique(budget_id, ynab_transaction_id)
  - constraint: unique(budget_id, import_id) where import_id is not null

## Business rules enforced by the tools

- GetUserInfo reads from users where status='active'; if token verification fails, set users.status='error' and populate last_error_code/last_error_message.
- ListBudgets returns budgets for the active user; budgets.status='archived' are excluded unless explicitly requested by an internal flag.
- GetBudgetDetails selects the most recently synced active budget for the user when no budget identifier is provided by the tool surface; if multiple budgets exist, the backend uses updated_at desc as a deterministic default.
- ListAccounts returns accounts for the selected budget where status in ('active','closed'); by default, closed=false accounts are returned unless an internal include_closed flag is set.
- ListPayees returns budget_entities where entity_type='payee' and status='active' for the selected budget.
- ListCategories returns budget_entities where entity_type='category' and status='active' for the selected budget; hidden categories are excluded by default.
- GetCategoryDetails fetches a single category by ynab_entity_id (or local id) within the selected budget and returns its current attributes and cached activity/budgeted fields when present.
- GetBudgetMonths returns budget_entities where entity_type='month' and status='active' for the selected budget ordered by month asc; the current month is determined by the user's locale but normalized/stored as the first day of month in UTC.
- GetCurrentMonthSnapshot uses the current month row in budget_entities (entity_type='month') plus an aggregate over transactions for that month by category_entity_id to compute a snapshot; if month cache fields are null, compute on read.
- ListAccountTransactions returns transactions filtered by account_id within the selected budget where status='active', ordered by date desc then updated_at desc; deleted transactions are excluded.
- SearchTransactions filters transactions within the selected budget where status='active' using case-insensitive containment on transactions.search_text; results are ordered by date desc and limited by an internal max (e.g., 200).
- GetRecentActivitySummary computes over transactions in the selected budget for a rolling window (e.g., last 30 days): total inflow/outflow, top payees by absolute outflow, and counts by cleared state; excludes status!='active'.
- GetIncomeVsExpenseSummary computes over transactions in the selected budget for the current month: income is sum(amount_milliunits>0), expense is abs(sum(amount_milliunits<0)); transfers (transfer_account_id not null) are excluded from both.
- Any sync operation that updates mirrored data must set the corresponding row status to 'syncing' at start and transition to 'active' (or 'sync_error') atomically; invalid transitions are rejected.
- FK integrity: accounts.budget_id must belong to a budget owned by the same user; transactions.budget_id and transactions.account_id must reference rows under the same budget, enforced by application-level checks on write.
- Quota/limits: SearchTransactions and transaction listing endpoints enforce a maximum page size (internal) and may require budgets.status='active' and users.status='active' to serve results.