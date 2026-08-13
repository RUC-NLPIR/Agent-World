# Superset Integration — local MCP environment

This backend stores connection/auth state to a Superset instance plus locally-cached Superset resources (databases, datasets, charts, dashboards, tags) and SQL Lab query executions for listing, lookup, and lifecycle actions like create/update/delete/stop. It supports workflows such as authenticating and refreshing tokens, browsing and mutating Superset objects, tagging objects, and executing/inspecting SQL Lab queries including async results export and retrieval.

Repository: https://github.com/aptro/superset-mcp
Homepage: https://smithery.ai/server/@aptro/superset-mcp

## Datastore

- `superset_instances.json` — Configured Superset instances this integration can talk to (base URL + connection settings). Used by config/base_url and as the root parent for all cached Superset resources. (12 rows; fields: ['id', 'base_url', 'display_name', 'api_prefix', 'verify_tls', 'default_timeout_ms', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(base_url)
  - constraint: default_timeout_ms BETWEEN 1000 AND 120000
- `auth_sessions.json` — Authentication material and session state for a Superset instance (access/refresh tokens and last validation). Drives auth_check_token_validity, auth_refresh_token, auth_authenticate_user, and me/roles calls. (12 rows; fields: ['id', 'superset_instance_id', 'username', 'access_token', 'refresh_token', 'token_type', 'access_token_expires_at', 'last_validated_at', 'last_validation_ok', 'last_error_code', 'last_error_message', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['anonymous', 'authenticated', 'expired', 'revoked', 'error']
  - constraint: foreign_key(superset_instance_id) references superset_instances(id) on delete cascade
  - constraint: token_type = 'bearer'
  - constraint: unique(superset_instance_id, username) where username is not null
- `superset_assets.json` — Locally cached Superset objects (databases, datasets, charts, dashboards, tags) plus temporary explore artifacts (form_data/permalink). Supports list/get/create/update/delete and tag association tools by storing external Superset IDs and JSON payloads. (30 rows; fields: ['id', 'superset_instance_id', 'asset_type', 'superset_object_id', 'superset_key', 'name', 'slug', 'database_asset_id', 'dataset_asset_id', 'schema_name', 'table_name', 'datasource_type', 'viz_type', 'payload', 'owners', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'stale']
  - constraint: foreign_key(superset_instance_id) references superset_instances(id) on delete cascade
  - constraint: unique(superset_instance_id, asset_type, superset_object_id) where superset_object_id is not null
  - constraint: unique(superset_instance_id, asset_type, superset_key) where superset_key is not null
  - constraint: asset_type in ('database','dataset','chart','dashboard','tag','saved_query','explore_form_data','explore_permalink')
- `tag_assignments.json` — Many-to-many association between tag assets and other Superset assets (dashboards/charts/datasets/databases). Powers tag_object_add/remove and tag_objects grouping. (30 rows; fields: ['id', 'superset_instance_id', 'tag_asset_id', 'object_asset_id', 'object_type', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: foreign_key(superset_instance_id) references superset_instances(id) on delete cascade
  - constraint: foreign_key(tag_asset_id) references superset_assets(id) on delete cascade
  - constraint: foreign_key(object_asset_id) references superset_assets(id) on delete cascade
  - constraint: unique(superset_instance_id, tag_asset_id, object_asset_id)
- `sql_lab_queries.json` — SQL Lab query executions and their lifecycle, including async result keys and export client IDs. Supports sqllab_execute_query, sqllab_get_results, sqllab_export_query_results, estimate_query_cost, query_list/get_by_id/stop, and saved_query create/get/list through linkage to superset_assets(saved_query). (45 rows; fields: ['id', 'superset_instance_id', 'database_asset_id', 'saved_query_asset_id', 'superset_query_id', 'client_id', 'result_key', 'sql', 'schema_name', 'cost_estimate', 'results_preview', 'row_count', 'duration_ms', 'error_message', 'status', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'success', 'failed', 'stopped', 'expired']
  - constraint: foreign_key(superset_instance_id) references superset_instances(id) on delete cascade
  - constraint: check(duration_ms is null or duration_ms >= 0)
  - constraint: check(row_count is null or row_count >= 0)
  - constraint: unique(superset_instance_id, client_id) where client_id is not null

## Business rules enforced by the tools

- superset_config_get_base_url returns superset_instances.base_url for the active instance; if multiple active instances exist, the server must deterministically choose one (e.g., lowest created_at) or require explicit instance selection (not present in tool surface).
- superset_auth_check_token_validity must call /api/v1/me and then update auth_sessions.last_validated_at and auth_sessions.last_validation_ok; on 401/403 it must set status to 'expired' (or 'revoked' if explicitly indicated) and clear access_token_expires_at if unknown.
- superset_auth_refresh_token may only run when auth_sessions.refresh_token is present; on success it must rotate access_token (and refresh_token if returned) and set status='authenticated'.
- superset_auth_authenticate_user with refresh=true must attempt: validate existing access_token; if invalid attempt refresh; if refresh fails then login with provided username/password. It must never overwrite a non-null stored username with null.
- For create/update/delete tools (dashboard/chart/database/dataset/tag/saved_query), on success the integration must upsert the corresponding superset_assets row keyed by (superset_instance_id, asset_type, superset_object_id) and set status='active'; on delete it must set status='deleted' rather than hard delete locally.
- superset_database_create/update must treat sqlalchemy_uri as secret: store only in superset_assets.payload if encrypted/secret-managed; otherwise store a redacted version and keep full URI out of logs and error_message fields.
- superset_database_get_tables/schemas/catalogs/function_names/connection/validate_sql/test_connection/validate_parameters do not create new persistent assets; they may attach response data to the related database asset in superset_assets.payload and update last_synced_at.
- superset_tag_object_add must find (or create) a tag asset by tag_name for the instance, then create or reactivate a tag_assignments row with status='active'; superset_tag_object_remove must set status='removed' (not delete) and must be idempotent.
- superset_tag_delete must set the tag asset status='deleted' and must set all tag_assignments for that tag to status='removed'.
- superset_explore_form_data_create and superset_explore_permalink_create must store key-based assets (asset_type explore_form_data/explore_permalink) with superset_key populated and payload containing the submitted form_data/state; retrieval by key must only return records for the same superset_instance_id.
- superset_sqllab_execute_query must create a sql_lab_queries row with status='queued' then transition to running/success/failed based on Superset response; it must persist client_id and result_key when returned.
- superset_sqllab_get_results must lookup sql_lab_queries by (superset_instance_id, result_key); if not present it may create a new row with status='success' and only result_key populated, but must still require a known superset_instance_id context.
- superset_sqllab_export_query_results must lookup sql_lab_queries by client_id; if not found it must return a not-found error rather than calling Superset blindly (prevents exporting someone else's unknown query id).
- superset_query_stop must only transition status from queued/running to stopped; it must be idempotent and must not change success/failed queries.
- superset_query_list and superset_activity_get_recent may cache returned objects into sql_lab_queries and/or superset_assets(payload) but must mark records stale rather than deleting anything missing from a page of results.