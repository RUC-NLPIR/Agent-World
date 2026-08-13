# Metabase Analytics Integration Server — local MCP environment

This backend stores a local representation of a Metabase instance (collections, dashboards, cards/questions, databases, tables, and fields) plus an execution/audit log for queries and card runs performed through the Integration Server. Core workflows include browsing Metabase metadata, creating/updating dashboards/cards/collections, and executing cards/SQL queries while recording results metadata for observability and troubleshooting.

Repository: https://github.com/cheukyin175/metabase-mcp
Homepage: https://smithery.ai/server/@cheukyin175/metabase-mcp

## Datastore

- `metabase_collections.json` — Mirrors Metabase Collections used to organize dashboards and cards. Supports listing and creation, plus referencing as the container for cards/dashboards. (31 rows; fields: ['id', 'metabase_collection_id', 'name', 'description', 'parent_metabase_collection_id', 'location_path', 'color', 'authority_level', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(metabase_collection_id)
  - constraint: name <> ''
  - constraint: parent_metabase_collection_id != metabase_collection_id
- `metabase_dashboards.json` — Mirrors Metabase Dashboards. Supports list/create/update/delete and acts as parent for dashboard-card placements. (27 rows; fields: ['id', 'metabase_dashboard_id', 'name', 'description', 'collection_id', 'metabase_collection_id', 'parameters_json', 'archived', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(metabase_dashboard_id)
  - constraint: name <> ''
  - constraint: archived = (status = 'archived') OR status IN ('active','deleted')
  - constraint: collection_id IS NULL OR metabase_collection_id IS NULL OR metabase_collection_id = (SELECT metabase_collection_id FROM metabase_collections WHERE id = collection_id)
- `metabase_cards.json` — Mirrors Metabase Cards (questions). Supports listing, creation, executing a card, and updating visualization settings. (36 rows; fields: ['id', 'metabase_card_id', 'name', 'description', 'collection_id', 'metabase_collection_id', 'database_id', 'metabase_database_id', 'dataset_query_json', 'display', 'visualization_settings_json', 'archived', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(metabase_card_id)
  - constraint: name <> ''
  - constraint: archived = (status = 'archived') OR status IN ('active','deleted')
  - constraint: collection_id IS NULL OR metabase_collection_id IS NULL OR metabase_collection_id = (SELECT metabase_collection_id FROM metabase_collections WHERE id = collection_id)
- `metabase_dashboard_cards.json` — Join table representing which cards appear on which dashboards (and their placement). Powers get_dashboard_cards and add_card_to_dashboard. (38 rows; fields: ['id', 'metabase_dashboard_card_id', 'dashboard_id', 'card_id', 'row', 'col', 'size_x', 'size_y', 'parameter_mappings_json', 'visualization_settings_json', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: unique(dashboard_id, card_id, status) WHERE status = 'active'
  - constraint: row IS NULL OR row >= 0
  - constraint: col IS NULL OR col >= 0
  - constraint: size_x IS NULL OR size_x >= 1
- `metabase_databases_schema.json` — Stores Metabase databases and their discovered schema (tables + fields) to support list_databases, list_tables, and get_table_fields. Tables/fields are stored as embedded arrays to keep the collection count low while still modeling the domain realistically. (12 rows; fields: ['id', 'metabase_database_id', 'name', 'engine', 'details_json', 'tables', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(metabase_database_id)
  - constraint: name <> ''
  - constraint: tables IS NOT NULL
  - constraint: json_schema(tables) validates: each table has {metabase_table_id:int, name:string, schema:string|null, description:string|null, fields:[{metabase_field_id:int, name:string, base_type:string|null, effective_type:string|null, semantic_type:string|null, fk_target_field_id:int|null, description:string|null, active:boolean}]}
- `metabase_executions.json` — Audit and result-metadata log for execute_query and execute_card calls. Stores request/response metadata, timing, row counts, and error details for observability. (36 rows; fields: ['id', 'execution_type', 'card_id', 'metabase_card_id', 'database_id', 'metabase_database_id', 'sql_text', 'parameters_json', 'result_format', 'result_metadata_json', 'row_count', 'runtime_ms', 'status', 'error_message', 'error_details_json', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: execution_type = 'card' => metabase_card_id IS NOT NULL
  - constraint: execution_type = 'query' => metabase_database_id IS NOT NULL
  - constraint: execution_type = 'query' => sql_text IS NOT NULL AND sql_text <> ''
  - constraint: runtime_ms IS NULL OR runtime_ms >= 0

## Business rules enforced by the tools

- list_dashboards returns metabase_dashboards where status != 'deleted'.
- delete_dashboard sets metabase_dashboards.status = 'deleted' and also sets metabase_dashboard_cards.status = 'removed' for all active placements referencing that dashboard_id (soft delete).
- list_cards returns metabase_cards where status != 'deleted'.
- list_collections returns metabase_collections where status != 'deleted'.
- create_collection inserts a new metabase_collections row with status='active' and must populate metabase_collection_id from Metabase response; uniqueness on metabase_collection_id must hold.
- create_dashboard inserts metabase_dashboards with status='active' and archived=false; metabase_dashboard_id must be recorded from Metabase response and be unique.
- update_dashboard may update name/description/collection association/parameters_json; if archived is set true then status must transition to 'archived' (and vice versa).
- get_dashboard_cards returns active rows from metabase_dashboard_cards for the given dashboard, joined to metabase_cards (excluding deleted cards).
- add_card_to_dashboard creates an active metabase_dashboard_cards row; if an active placement already exists for (dashboard_id, card_id) it must be rejected or idempotently returned.
- create_card inserts metabase_cards with status='active' and archived=false; must store metabase_card_id from Metabase response; must store dataset_query_json and metabase_database_id when provided.
- update_card_visualization updates metabase_cards.visualization_settings_json and optionally metabase_cards.display; updated_at must change.
- list_databases returns metabase_databases_schema where status='active'.
- list_tables for a database is served from metabase_databases_schema.tables[*] filtered by metabase_database_id.
- get_table_fields for a table is served from metabase_databases_schema.tables[*].fields[*] matching metabase_table_id; only fields with active=true should be returned.
- execute_query must create a metabase_executions row (execution_type='query') in status 'queued' then transition through 'running' to a terminal state; it must reference metabase_database_id and store sql_text (redacted if configured).
- execute_card must create a metabase_executions row (execution_type='card') referencing metabase_card_id (and card_id when known) and follow the same status transition rules as execute_query.
- An execution in a terminal state (succeeded/failed/cancelled) cannot transition to any other state.
- Foreign key integrity: metabase_dashboard_cards.dashboard_id must reference an existing non-deleted dashboard; metabase_dashboard_cards.card_id must reference an existing non-deleted card at insert time.
- Uniqueness mapping: metabase_*_id fields that mirror Metabase identifiers (metabase_collection_id, metabase_dashboard_id, metabase_card_id, metabase_database_id) must be unique within this Integration Server instance.