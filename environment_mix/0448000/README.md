# PocketBase MCP Server — local MCP environment

This backend stores a PocketBase instance control-plane: collection schemas, generic records (with dynamic fields), attached files, migration files and their apply/revert history, plus API request logs and aggregated stats. Main workflows include CRUD on records across arbitrary collections, file upload/download bound to record fields, generating and applying migrations that change collection schemas, and querying request logs for troubleshooting and usage analysis.

Repository: https://github.com/mabeldata/pocketbase-mcp
Homepage: https://smithery.ai/server/@mabeldata/pocketbase-mcp

## Datastore

- `pb_collections.json` — PocketBase collection definitions (schema + rules). Used to list collections and fetch collection schema; also targeted by schema migrations. (30 rows; fields: ['id', 'name', 'type', 'system', 'schema', 'indexes', 'list_rule', 'view_rule', 'create_rule', 'update_rule', 'delete_rule', 'options', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(name)
  - constraint: type in ('base','auth','view')
  - constraint: system implies status != 'deleted' unless explicitly dropped by migration
  - constraint: schema is a JSON array of field objects with unique field.name within the collection
- `pb_records.json` — Generic record storage for all non-view collections. Record dynamic fields are stored in `data`; file attachments are represented in pb_files and referenced by data field values (PocketBase convention). (35 rows; fields: ['id', 'collection_id', 'collection_name', 'data', 'expand', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(collection_id) references pb_collections(id) on delete restrict unless migration drop cascade
  - constraint: collection_name must equal pb_collections.name for the referenced collection_id
  - constraint: status in ('active','deleted')
  - constraint: data must satisfy the owning collection schema (required fields present, types match, unique constraints enforced where applicable)
- `pb_files.json` — File blobs/metadata attached to record fields. Supports upload (content string -> stored blob) and download (returns URL/path) operations. (37 rows; fields: ['id', 'collection_id', 'record_id', 'field_name', 'original_filename', 'stored_filename', 'content_type', 'size_bytes', 'sha256', 'storage_backend', 'storage_path', 'public_url', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(record_id) references pb_records(id) on delete cascade
  - constraint: fk(collection_id) references pb_collections(id)
  - constraint: size_bytes >= 0 and size_bytes <= 536870912
  - constraint: unique(record_id, field_name, stored_filename)
- `pb_migrations.json` — Migration files management, including configured migrations directory, file contents, and apply/revert history. Supports creating migration files, listing them, applying/reverting one or many, and reverting to a target. (37 rows; fields: ['id', 'migrations_dir', 'filename', 'name', 'kind', 'target_collection_id', 'target_collection_name', 'payload', 'up_sql_or_code', 'down_sql_or_code', 'status', 'applied_at', 'reverted_at', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'applied', 'reverted', 'failed']
  - constraint: unique(migrations_dir, filename)
  - constraint: kind in ('empty','create_collection','add_field','custom')
  - constraint: if kind='create_collection' then target_collection_name is not null
  - constraint: if kind='add_field' then target_collection_id is not null and payload contains field definition
- `pb_api_logs.json` — API request/response logs for PocketBase endpoints. Supports listing logs with filters/sort/pagination, fetching by id, and computing stats. (34 rows; fields: ['id', 'request_id', 'method', 'path', 'query', 'status_code', 'duration_ms', 'ip', 'user_agent', 'auth_record_id', 'collection_id', 'record_id', 'error', 'created_at', 'updated_at'])
  - lifecycle `method`: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD']
  - constraint: status_code >= 100 and status_code <= 599
  - constraint: duration_ms >= 0 and duration_ms <= 3600000
  - constraint: index(created_at), index(path), index(status_code), index(collection_id, record_id)
  - constraint: log retention: rows older than configured retention window may be purged (not represented as status)

## Business rules enforced by the tools

- list_collections reads from pb_collections where status != 'deleted', ordered by name unless caller specifies otherwise.
- get_collection_schema requires an existing pb_collections row; returned schema includes schema, rules, indexes, type, system, options.
- create_record inserts into pb_records with collection_id resolved by collection name; validates pb_collections.status='active' and pb_collections.type != 'view'.
- update_record updates pb_records.data and updated_at; rejects updates when pb_records.status='deleted' or owning pb_collections.status!='active'.
- fetch_record reads pb_records by (collection, id) and may compute expansion based on relation fields from pb_collections.schema; any persisted expand cache must never be treated as source of truth.
- list_records supports filter/sort/pagination against pb_records for a given collection; filters may reference system fields (id, created_at, updated_at) and keys inside data; page/perPage must be bounded (perPage <= 200).
- upload_file creates pb_files row, stores blob to storage_backend, and updates pb_records.data[field_name] according to field type (single: string filename; multiple: array of filenames).
- download_file returns a signed/constructed URL derived from pb_files.storage_backend + storage_path, only if pb_files.status='active' and associated record is not deleted.
- set_migrations_directory sets the active directory value by writing it into pb_migrations.migrations_dir for newly created migrations; directory must be under an allowed base path.
- create_migration creates a pb_migrations row with kind='empty', status='draft', and a unique timestamped filename in migrations_dir.
- create_collection_migration creates a pb_migrations row with kind='create_collection', payload containing the full collection definition, and status='draft'; applying it must create a pb_collections row.
- add_field_migration creates a pb_migrations row with kind='add_field', target_collection_id set, payload containing a single field definition; applying it must update pb_collections.schema and enforce uniqueness of field names.
- list_migrations lists pb_migrations by migrations_dir and filename ascending; status reflects current applied/reverted state.
- apply_migration can only transition pb_migrations.status from 'draft' or 'reverted' to 'applied'; on success sets applied_at and clears last_error; on failure sets status='failed' and last_error.
- revert_migration can only revert migrations currently in status='applied'; on success sets reverted_at and status='reverted'.
- apply_all_migrations applies all migrations in status in ('draft','reverted') ordered by filename, stopping on first failure and leaving subsequent migrations untouched.
- revert_to_migration(target) reverts all applied migrations with filename greater than the target migration's filename (same migrations_dir), in reverse order; target may be kept applied.
- list_logs queries pb_api_logs with filtering (by date range, method, status_code, path, collection_id, record_id) and pagination; page size must be bounded (perPage <= 500).
- get_log fetches a single pb_api_logs row by id; returns 404 if missing.
- get_logs_stats aggregates pb_api_logs over a filter scope, returning counts by status_code class (2xx/4xx/5xx), total requests, and avg/p95 duration_ms computed from duration_ms.