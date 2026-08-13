# Xano MCP Server — local MCP environment

This backend stores a local representation of Xano resources (instances, workspaces, tables, schemas, indexes, APIs, files, request history, and exports) so the MCP server can list, inspect, and mutate them via the tool surface. The primary workflows are: discover instance/workspace metadata; manage tables (CRUD + schema changes + indexes); manage records (CRUD + bulk + search + truncate); manage files and API groups/APIs; and audit activity via request history and export jobs.

Repository: https://github.com/roboulos/simple-xano-mcp
Homepage: https://smithery.ai/server/@roboulos/simple-xano-mcp

## Datastore

- `xano_instances.json` — Known Xano instances reachable by this MCP server (used as the root scope for all other resources). (18 rows; fields: ['id', 'instance_name', 'display_name', 'base_url', 'region', 'status', 'last_discovered_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(instance_name)
  - constraint: status in ('active','disabled','deleted')
  - constraint: base_url is null or base_url like 'http%'
- `xano_workspaces.json` — Workspaces/databases inside an instance (Xano calls them workspaces; tool docs call them databases/workspaces). (18 rows; fields: ['id', 'instance_id', 'xano_workspace_id', 'name', 'branch_default', 'status', 'meta', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: fk(instance_id) references xano_instances(id)
  - constraint: unique(instance_id, xano_workspace_id)
  - constraint: xano_workspace_id > 0
  - constraint: branch_default is null or length(branch_default) between 1 and 64
- `xano_tables.json` — Tables within a workspace, including schema and indexes needed for table/schema/index tools and record operations. (18 rows; fields: ['id', 'workspace_id', 'xano_table_id', 'name', 'description', 'docs', 'auth_required', 'tags', 'status', 'schema', 'indexes', 'pk_field_name', 'pk_next_value', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleting', 'deleted']
  - constraint: fk(workspace_id) references xano_workspaces(id)
  - constraint: unique(workspace_id, xano_table_id)
  - constraint: unique(workspace_id, name) where status != 'deleted'
  - constraint: xano_table_id > 0
- `xano_table_records.json` — Row-level data for tables (supports browse/get/search/create/update/delete and bulk operations). Stores each record as JSON plus extracted primary key value. (18 rows; fields: ['id', 'table_id', 'pk_value', 'record_data', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(table_id) references xano_tables(id)
  - constraint: unique(table_id, pk_value)
  - constraint: pk_value != ''
  - constraint: status in ('active','deleted')
- `xano_workspace_artifacts.json` — Workspace-scoped operational artifacts: files, request history, export jobs, API groups, and APIs. Collapsed into one collection to stay within the 3–6 collections requirement while still mapping all tools. (18 rows; fields: ['id', 'workspace_id', 'artifact_type', 'branch', 'xano_object_id', 'parent_artifact_id', 'name', 'description', 'docs', 'swagger_enabled', 'guid', 'canonical_url', 'access', 'size_bytes', 'content_type', 'download_url', 'password_protected', 'payload', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'processing', 'deleted', 'failed']
  - constraint: fk(workspace_id) references xano_workspaces(id)
  - constraint: fk(parent_artifact_id) references xano_workspace_artifacts(id)
  - constraint: artifact_type in ('file','request_history','export_job','api_group','api')
  - constraint: unique(workspace_id, artifact_type, xano_object_id) where xano_object_id is not null and status != 'deleted'

## Business rules enforced by the tools

- All tool calls that include instance_name must resolve to exactly one xano_instances row with status='active'; otherwise return a not-found/disabled error.
- workspace_id/table_id/apigroup_id/api_id/file_id/query_id parameters may be provided as string or number, but must be validated as positive integers when mapped to xano_*_id fields.
- xano_list_databases returns rows from xano_workspaces filtered by instance_id (resolved from instance_name) and status!='deleted'.
- xano_get_workspace_details reads xano_workspaces by (instance_id, xano_workspace_id).
- xano_list_tables returns xano_tables by workspace_id (mapped from xano_workspaces.xano_workspace_id) and status!='deleted'.
- xano_create_table inserts xano_tables with status='active', initializes schema with at least the primary key field, and enforces unique(workspace_id, name) among non-deleted tables.
- xano_update_table may change name/description/docs/auth_required/tags but must not set status to 'deleted' directly; deletion uses xano_delete_table which transitions status to 'deleting' then 'deleted'.
- xano_get_table_schema returns xano_tables.schema; xano_add_field_to_schema / xano_rename_schema_field / xano_delete_field mutate xano_tables.schema and must reject operations that would remove/rename the primary key field or create duplicate field names.
- xano_list_indexes returns xano_tables.indexes; create_*_index appends a new index entry and must validate that referenced field names exist in schema and that index field ops are only 'asc' or 'desc'.
- xano_create_unique_index must enforce that existing active records do not violate the uniqueness constraint before marking the index active.
- xano_delete_index removes or marks deleted the matching index entry identified by index_id within xano_tables.indexes.
- xano_browse_table_content returns active xano_table_records for the table ordered by pk_value (or a default ordering) with pagination (page>=1, per_page between 1 and 200; default per_page=50).
- xano_get_table_record reads xano_table_records by (table_id, pk_value) where status='active'.
- xano_create_table_record inserts into xano_table_records; if the client supplies the pk field in record_data it must match pk_value and must not conflict with existing pk_value.
- xano_update_table_record updates record_data and updated_at for the addressed pk_value; must not change pk_value unless Xano supports it (default: forbid pk changes).
- xano_delete_table_record sets xano_table_records.status='deleted' (or hard-deletes) and must ensure subsequent gets do not return it.
- xano_bulk_create_records inserts multiple xano_table_records atomically; if allow_id_field=false, any provided pk field in input records must be ignored/rejected; duplicates within the batch or against existing data must fail the batch.
- xano_bulk_update_records applies updates atomically per request; each update operation must include row_id (mapped to pk_value) and a partial record_data merge.
- xano_bulk_delete_records marks addressed pk_values deleted (or removes them) and returns counts of deleted vs not_found.
- xano_truncate_table deletes/marks deleted all records for the table; if reset=true then xano_tables.pk_next_value is reset to 1 (or null depending on pk strategy).
- xano_search_table_content evaluates search_conditions against xano_table_records.record_data for active records, applies sort if provided (sort values restricted to 'asc'|'desc'), and paginates results.
- xano_list_files reads xano_workspace_artifacts where artifact_type='file' and status='active', filtered by access/search, sorted by requested sort (created_at|name) with pagination limits identical to table browse.
- xano_get_file_details reads a single file artifact by (workspace_id, xano_object_id) with artifact_type='file'.
- xano_delete_file marks the file artifact status='deleted'; xano_bulk_delete_files marks multiple file artifacts deleted and must be idempotent.
- xano_browse_request_history reads artifacts where artifact_type='request_history' filtered by optional branch/api_id/query_id (stored in branch and payload.*), with pagination.
- xano_export_workspace and xano_export_workspace_schema create an artifact_type='export_job' row with status='processing', store branch and password_protected flag, and later transition to status='active' with a download_url or to status='failed'. Plaintext password must never be stored.
- xano_browse_api_groups reads artifacts where artifact_type='api_group' filtered by branch/search and sortable by created_at|updated_at|name; deleted groups are excluded.
- xano_get_api_group reads one api_group artifact by xano_object_id.
- xano_create_api_group inserts an api_group artifact with swagger_enabled, docs, description, branch (defaulting from workspace.branch_default), status='active'.
- xano_update_api_group updates name/description/docs/swagger_enabled; xano_delete_api_group marks status='deleted' and must also mark child api artifacts (parent_artifact_id) as deleted or orphan-preventing.
- xano_update_api_group_security updates guid and canonical_url; guid must be unique per (workspace_id, artifact_type) among non-deleted rows when present.
- xano_browse_apis_in_group reads artifacts where artifact_type='api' and parent_artifact_id points to the specified api_group; supports pagination/search/sort.
- xano_get_api reads an api artifact by (workspace_id, parent api_group, api_id).
- xano_create_api inserts an api artifact under a parent api_group; xano_update_api updates name/description/payload fields; xano_delete_api marks status='deleted'.
- xano_update_api_security updates guid for api artifacts; guid must be unique among non-deleted apis within the workspace when present.