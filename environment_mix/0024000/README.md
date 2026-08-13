# Airtable Server — local MCP environment

This backend stores Airtable-like workspaces (“bases”) containing tables with user-defined schema (fields) and row data (records). The main workflows are: discover bases/tables, mutate schema (create/update tables and fields), and CRUD/search records while preserving schema constraints and soft-delete/history semantics where appropriate.

Repository: https://github.com/felores/airtable-mcp
Homepage: https://smithery.ai/server/airtable-server

## Datastore

- `bases.json` — Top-level container similar to an Airtable base. Tables belong to a base; tools like list_bases and list_tables are served from this and related collections. (18 rows; fields: ['id', 'name', 'status', 'owner_user_id', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(name, owner_user_id) where status != 'deleted'
  - constraint: name length between 1 and 255
  - constraint: metadata is valid JSON object
- `tables.json` — Table definitions within a base. Served by list_tables; mutated by create_table and update_table. (18 rows; fields: ['id', 'base_id', 'name', 'description', 'primary_field_id', 'schema_version', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: foreign key (base_id) references bases(id) on delete restrict
  - constraint: unique(base_id, name) where status != 'deleted'
  - constraint: name length between 1 and 255
  - constraint: schema_version >= 1
- `fields.json` — User-defined column schema for a table. Served/mutated by create_field and update_field; used to validate record writes and to drive search. (18 rows; fields: ['id', 'table_id', 'name', 'type', 'options', 'is_required', 'is_unique', 'is_indexed', 'position', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'hidden', 'deleted']
  - constraint: foreign key (table_id) references tables(id) on delete restrict
  - constraint: unique(table_id, name) where status != 'deleted'
  - constraint: position >= 1
  - constraint: options is valid JSON object
- `records.json` — Row-level entities within a table. Served/mutated by list_records, create_record, update_record, delete_record, get_record. Field values are stored in a JSON object keyed by field_id. (18 rows; fields: ['id', 'table_id', 'fields', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key (table_id) references tables(id) on delete restrict
  - constraint: fields is valid JSON object
  - constraint: if status = 'deleted' then deleted_at is not null
  - constraint: cannot update records in tables with status != 'active'
- `record_search_index.json` — Denormalized per-record search document used by search_records for fast filtering/full-text search across indexed fields. Updated asynchronously on record/field changes and schema_version increments. (18 rows; fields: ['id', 'table_id', 'record_id', 'schema_version', 'status', 'search_text', 'search_kv', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'deleted']
  - constraint: foreign key (table_id) references tables(id) on delete restrict
  - constraint: foreign key (record_id) references records(id) on delete cascade
  - constraint: unique(table_id, record_id)
  - constraint: schema_version >= 1

## Business rules enforced by the tools

- list_bases returns bases where status != 'deleted'.
- list_tables requires a base_id context (implementation-provided); it returns tables for that base where status != 'deleted'.
- create_table inserts into tables with status='active' and schema_version=1 and also creates a default primary field in fields; tables.primary_field_id must reference that created field.
- update_table may change name/description/status; renaming enforces unique(base_id,name) among non-deleted tables; archiving a table prevents create_record/update_record/delete_record until unarchived.
- create_field inserts a new fields row with status='active' and increments tables.schema_version by 1; if table has no primary_field_id, the first writable text-like field created becomes primary_field_id.
- update_field may change name/options/is_required/is_unique/is_indexed/position/status and increments tables.schema_version by 1; field type changes are only allowed if all existing active records can be coerced/validated or the operation is rejected.
- list_records requires table_id context; returns records where status='active' by default; if the server supports including deleted, it must be explicit.
- create_record inserts records.status='active' and validates values against fields schema (types/options, required, unique) within the same transaction.
- update_record updates records.fields and updated_at and validates against current active fields; it must reject writes to read-only field types (formula/lookup/createdTime/lastModifiedTime).
- delete_record transitions records.status from 'active' to 'deleted' and sets deleted_at; repeated deletes are idempotent.
- get_record fetches by record_id and must ensure record.table_id matches the requested table context (if provided) and record.status='active' unless explicitly requested otherwise.
- search_records uses record_search_index for tables with schema_version matching; if index is stale or missing, the server either reindexes synchronously for the requested records or falls back to scanning records.fields for indexed fields.
- record_search_index rows are created/updated after any create_record/update_record/delete_record or any schema change that affects is_indexed fields; schema changes mark existing index rows for that table as status='stale'.
- Foreign key integrity: a base cannot be deleted if it has non-deleted tables unless deletion is a soft delete that cascades statuses; a table cannot be deleted if it has active fields unless soft deletion cascades field status to deleted.
- Uniqueness enforcement for is_unique fields applies only among records where status='active' and only for fields with scalar comparable values; null/empty values do not violate uniqueness unless options.enforce_unique_nulls=true (default false).