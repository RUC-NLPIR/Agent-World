# Supabase MCP Server — local MCP environment

This backend stores metadata and operational history for Supabase projects managed via the MCP server: database schema/migrations, SQL execution history, Edge Functions deployments, and development branches. The main workflows are (1) inspect project DB state (tables/extensions/migrations), (2) apply migrations and execute SQL, (3) deploy/version Edge Functions, (4) create/manage/merge/reset/rebase dev branches, and (5) fetch recent logs and project connection details (URL/anon key).

Repository: https://github.com/supabase-community/supabase-mcp
Homepage: https://smithery.ai/server/@supabase-community/supabase-mcp

## Datastore

- `projects.json` — Supabase projects (production and branch projects) known to the MCP server, including connection metadata (API URL) and API keys required by tools like get_project_url/get_anon_key. Branch projects reference their parent production project. (17 rows; fields: ['id', 'project_ref', 'name', 'environment', 'parent_project_id', 'region', 'api_url', 'db_host', 'db_name', 'anon_key', 'service_role_key', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleting']
  - constraint: unique(project_ref)
  - constraint: environment='branch' implies parent_project_id is not null
  - constraint: environment='production' implies parent_project_id is null
  - constraint: api_url starts_with 'https://'
- `schema_introspection_snapshots.json` — Cached results of schema introspection per project to serve list_tables, list_extensions, and list_migrations efficiently and consistently. Snapshots are immutable once completed, and the latest completed snapshot per project is used for reads. (20 rows; fields: ['id', 'project_id', 'source', 'pg_version', 'tables', 'extensions', 'migrations', 'status', 'error_message', 'started_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['running', 'completed', 'failed']
  - constraint: tables is array
  - constraint: extensions is array
  - constraint: migrations is array
  - constraint: completed_at is not null when status='completed'
- `db_operations.json` — History of database-changing or database-reading operations invoked by MCP tools, including apply_migration, execute_sql, and generate_typescript_types. Stores inputs/outputs, provides auditability, and drives follow-up introspection snapshots. (21 rows; fields: ['id', 'project_id', 'tool_name', 'operation_kind', 'sql_text', 'migration_name', 'migration_version', 'migration_checksum', 'params', 'result', 'stdout', 'stderr', 'error_message', 'status', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: tool_name in ('apply_migration','execute_sql','generate_typescript_types')
  - constraint: tool_name='execute_sql' implies sql_text is not null
  - constraint: tool_name='apply_migration' implies operation_kind='ddl'
  - constraint: operation_kind in ('ddl','dml','read','types')
- `edge_functions.json` — Edge Functions defined in a project. list_edge_functions reads from this table; deploy_edge_function creates new versions via edge_function_versions and updates the active version pointer. (18 rows; fields: ['id', 'project_id', 'slug', 'description', 'entrypoint_path', 'active_version_id', 'runtime', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(project_id, slug)
  - constraint: slug matches ^[a-z0-9][a-z0-9_-]{0,62}$
  - constraint: runtime in ('deno-edge')
- `edge_function_versions.json` — Immutable deployment versions for Edge Functions. deploy_edge_function appends a version and can mark it active on the parent edge_functions row. merge_branch copies versions from a branch project into production. (18 rows; fields: ['id', 'function_id', 'project_id', 'version_number', 'source_bundle_sha256', 'source_text', 'deploy_metadata', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['building', 'deployed', 'failed', 'superseded']
  - constraint: unique(function_id, version_number)
  - constraint: version_number >= 1
  - constraint: length(source_text) <= 500000
  - constraint: error_message is not null when status='failed'
- `branches.json` — Development branches for a production Supabase project. create_branch creates a branch and a corresponding branch project record; list_branches reads from here; delete_branch/merge_branch/reset_branch/rebase_branch mutate status and record operation history pointers. (17 rows; fields: ['id', 'production_project_id', 'branch_project_id', 'name', 'created_by', 'last_operation_id', 'status', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['creating', 'ready', 'merging', 'rebasing', 'resetting', 'deleting', 'deleted', 'failed']
  - constraint: unique(production_project_id, name)
  - constraint: unique(branch_project_id)
  - constraint: production_project_id != branch_project_id
  - constraint: status in ('creating','ready','merging','rebasing','resetting','deleting','deleted','failed')

## Business rules enforced by the tools

- list_tables/list_extensions/list_migrations must read from the latest schema_introspection_snapshots row for the given project_id with status='completed'; if none exists, the system must create a new snapshot (status='running') and complete it before returning results.
- apply_migration must create a db_operations row with tool_name='apply_migration' and operation_kind='ddl', transitioning status queued->running->(succeeded|failed). On success it must trigger creation of a new schema_introspection_snapshots row with source='post_migration'.
- execute_sql must reject statements classified as DDL (CREATE/ALTER/DROP/TRUNCATE, etc.) and require apply_migration for DDL; execute_sql must create a db_operations row with tool_name='execute_sql' and operation_kind in ('read','dml') based on the statement.
- generate_typescript_types must create a db_operations row with tool_name='generate_typescript_types' and operation_kind='types'; the generated artifact metadata (e.g., file size, checksum) must be stored in db_operations.result.
- deploy_edge_function must upsert edge_functions (unique by project_id+slug) and append a new edge_function_versions row with version_number = previous_max+1; only one version per function may be active via edge_functions.active_version_id, and activating a new version must set the prior active version status to 'superseded'.
- create_branch must create a projects row for the branch (environment='branch', parent_project_id set) and a branches row linking production_project_id to branch_project_id; branches.status must start at 'creating' and only become 'ready' once all production migrations are reflected in the branch snapshot.
- list_branches must return branches for a production_project_id ordered by created_at desc and include status reflecting any in-progress operations (merging/rebasing/resetting/deleting).
- delete_branch must transition branches.status to 'deleting' and then 'deleted'; once deleted, the corresponding branch projects.status must transition to 'deleting' then be removed/disabled; operations against deleted branches must be rejected.
- merge_branch must be allowed only when branches.status='ready'; it must copy/apply pending migrations and Edge Function versions from branch_project_id into production_project_id, then return branch to status='ready' (or 'failed' with last_error).
- reset_branch must be allowed only when branches.status='ready'; it must discard untracked schema/data changes by recreating the branch DB state from production migrations, and must create a fresh schema_introspection_snapshots row for the branch with source='post_migration'.
- rebase_branch must be allowed only when branches.status='ready'; it must apply any production migrations not present on the branch and then refresh the branch snapshot; if migration checksum conflicts are detected, operation must fail and set branches.status='failed'.
- get_project_url and get_anon_key must only return data for projects.status='active'; if status!='active', the tools must error.
- get_logs must only return logs within the last 60 seconds; the backend should enforce this by querying an external log provider and must not persist full logs beyond an ephemeral cache (if cached at all), meaning no durable collection is required for logs in this model.