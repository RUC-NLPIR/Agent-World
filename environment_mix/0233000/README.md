# Neon Database — local MCP environment

This backend stores Neon account state for projects and their branches, plus operational artifacts for SQL execution and managed schema migrations. Core workflows include provisioning projects/branches, running SQL (single statements or transactions) against a selected branch/database, introspecting branch/table metadata, generating/applying migrations via temporary branches, and provisioning Stack Auth integration for a project.

Repository: https://github.com/neondatabase/mcp-server-neon
Homepage: https://smithery.ai/server/neon

## Datastore

- `projects.json` — Neon projects owned by an account. A project is the top-level container for branches, logical databases, and integrations. (29 rows; fields: ['id', 'account_id', 'name', 'region', 'postgres_version', 'default_branch_id', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['provisioning', 'active', 'deleting', 'deleted', 'error']
  - constraint: unique(account_id, name) WHERE deleted_at IS NULL
  - constraint: postgres_version IN (14,15,16,17)
  - constraint: status != 'active' OR default_branch_id IS NOT NULL
- `branches.json` — Branches within a Neon project, including main and ephemeral branches created for migrations. Used for introspection and for routing SQL execution. (31 rows; fields: ['id', 'project_id', 'name', 'parent_branch_id', 'is_default', 'is_temporary', 'temporary_reason', 'compute_size', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['creating', 'ready', 'deleting', 'deleted', 'error']
  - constraint: unique(project_id, name) WHERE deleted_at IS NULL
  - constraint: is_default = true implies name = 'main' OR projects.default_branch_id = id
  - constraint: parent_branch_id IS NULL OR parent_branch_id references branches.id AND branches.project_id = project_id
  - constraint: compute_size IS NULL OR compute_size IN ('nano','micro','small','medium','large','xlarge')
- `database_endpoints.json` — Resolved connection targets per (project, branch, database). Stores host/port and default role/database names used to generate connection strings and execute SQL. (30 rows; fields: ['id', 'project_id', 'branch_id', 'database_name', 'default_role', 'host', 'port', 'ssl_mode', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['provisioning', 'available', 'unavailable', 'deleted']
  - constraint: unique(project_id, branch_id, database_name) WHERE status != 'deleted'
  - constraint: port IN (5432,5433)
  - constraint: ssl_mode IN ('require','verify-full','disable')
  - constraint: branch_id references branches.id AND branches.project_id = project_id
- `sql_executions.json` — Audit log of SQL statements and transactions executed via the API, including results metadata and error capture. Powers run_sql and run_sql_transaction and supports operational debugging. (36 rows; fields: ['id', 'project_id', 'branch_id', 'endpoint_id', 'database_name', 'role', 'type', 'statements', 'parameters', 'status', 'started_at', 'completed_at', 'duration_ms', 'rows_affected', 'result_preview', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: branch_id references branches.id AND branches.project_id = project_id
  - constraint: endpoint_id references database_endpoints.id AND database_endpoints.branch_id = branch_id
  - constraint: type IN ('single','transaction')
  - constraint: type = 'single' implies array_length(statements)=1
- `migrations.json` — Generated and applied schema migrations coordinated via temporary branches. prepare_database_migration creates a migration record and a temporary branch; complete_database_migration applies changes to main and deletes the temp branch. (36 rows; fields: ['id', 'project_id', 'source_branch_id', 'temp_branch_id', 'database_name', 'prompt', 'generated_ddl', 'dry_run_summary', 'prepare_sql_execution_id', 'apply_sql_execution_id', 'status', 'error_message', 'temp_branch_deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['preparing', 'ready_for_review', 'applying', 'completed', 'failed', 'cancelled']
  - constraint: source_branch_id references branches.id AND branches.project_id = project_id
  - constraint: temp_branch_id references branches.id AND branches.project_id = project_id
  - constraint: source_branch_id != temp_branch_id
  - constraint: array_length(generated_ddl) >= 1
- `auth_integrations.json` — Provisioned authentication integrations for Neon projects, specifically Stack Auth (@stackframe/stack). Stores configuration and provisioning state. (15 rows; fields: ['id', 'project_id', 'provider', 'stack_project_id', 'stack_env', 'callback_urls', 'secrets_ref', 'status', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['provisioning', 'active', 'error', 'disabled']
  - constraint: unique(project_id, provider)
  - constraint: provider = 'stack'
  - constraint: status = 'active' implies stack_project_id IS NOT NULL AND secrets_ref IS NOT NULL

## Business rules enforced by the tools

- list_projects returns projects where account_id matches the caller and deleted_at IS NULL.
- create_project creates a projects row in status='provisioning', creates an initial 'main' branch in status='creating', then sets projects.default_branch_id to that branch once it becomes ready; project transitions to status='active' only after main branch and at least one database_endpoints row are available.
- delete_project sets projects.status='deleting' then 'deleted' and sets deleted_at; all branches for the project transition to deleting/deleted and get deleted_at set (soft-delete).
- create_branch requires projects.status='active' and a parent_branch_id that belongs to the same project and is status='ready'; it creates a branches row with status='creating' and later 'ready'.
- delete_branch is forbidden if branches.is_default=true; otherwise it transitions status to 'deleting' then 'deleted' and sets deleted_at; associated database_endpoints transition to status='deleted'.
- describe_project returns the project plus its branches and default_branch_id; it must not return projects with deleted_at set unless caller explicitly has internal privileges.
- describe_branch returns a computed tree view of objects by querying the actual Postgres catalog through run_sql-like execution; the backend may cache the rendered tree (not required to be stored) but must ensure branch.status='ready'.
- get_database_tables and describe_table_schema execute catalog queries against the selected (branch_id,database_name) via sql_executions; branch must be status='ready' and endpoint must be status='available'.
- run_sql creates a sql_executions row with type='single' and exactly one statement; run_sql_transaction creates type='transaction' with 2+ statements; both require project status='active', branch status='ready', endpoint status='available'.
- SQL execution rows are immutable for statements/parameters after status moves from 'queued' to 'running'; only status/timing/result/error fields may change thereafter.
- prepare_database_migration creates a migrations row, creates an is_temporary=true branch (temp_branch_id) derived from source_branch_id, generates DDL into generated_ddl, executes DDL on the temporary branch (prepare_sql_execution_id), and sets migrations.status='ready_for_review' if execution succeeded else 'failed'.
- complete_database_migration is allowed only when migrations.status='ready_for_review'; it applies generated_ddl to source_branch_id (apply_sql_execution_id), sets status='completed' on success, and deletes the temporary branch (temp_branch_deleted_at set, branches.status='deleted').
- complete_database_migration must be idempotent: repeated calls after status='completed' must not re-apply DDL and must report the temp branch as deleted.
- get_connection_string builds a connection string from database_endpoints plus optional overrides for role/database/ssl; it must not return secrets, only a formatted DSN and/or parameters; endpoint must be available and branch ready.
- provision_neon_auth creates or updates exactly one auth_integrations row per project/provider='stack'; it transitions status to 'provisioning' and then to 'active' only after stack_project_id and secrets_ref are stored.