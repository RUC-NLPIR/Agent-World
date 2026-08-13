# DynamoDB Server — local MCP environment

This backend models a DynamoDB-like service that manages tables, their capacity/index configuration, and the items stored inside them. Primary workflows include creating and describing tables, listing tables, changing provisioned throughput on tables and GSIs, creating secondary indexes, and performing item read/write/update plus query/scan operations with filtering.

Repository: https://github.com/imankamyabi/dynamodb-mcp-server
Homepage: https://smithery.ai/server/@imankamyabi/dynamodb-mcp-server

## Datastore

- `ddb_tables.json` — DynamoDB table metadata: schema, capacity mode, provisioned throughput, and lifecycle status. Serves create_table, describe_table, list_tables, update_capacity. (17 rows; fields: ['table_id', 'table_name', 'account_id', 'region', 'billing_mode', 'read_capacity_units', 'write_capacity_units', 'hash_key_name', 'hash_key_type', 'range_key_name', 'range_key_type', 'item_count_estimate', 'table_size_bytes_estimate', 'status', 'status_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['CREATING', 'ACTIVE', 'UPDATING', 'DELETING', 'FAILED']
  - constraint: unique(account_id, region, table_name)
  - constraint: hash_key_name <> ''
  - constraint: hash_key_type in ('S','N','B')
  - constraint: range_key_name is null OR range_key_name <> ''
- `ddb_indexes.json` — Secondary index definitions for tables (GSI/LSI), including key schema and (for GSIs) capacity. Serves create_gsi, update_gsi, create_lsi and describe_table. (18 rows; fields: ['index_id', 'table_id', 'index_name', 'index_type', 'hash_key_name', 'hash_key_type', 'range_key_name', 'range_key_type', 'projection_type', 'non_key_attributes', 'read_capacity_units', 'write_capacity_units', 'status', 'status_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['CREATING', 'ACTIVE', 'UPDATING', 'DELETING', 'FAILED']
  - constraint: foreign_key(table_id) references ddb_tables(table_id) on delete cascade
  - constraint: unique(table_id, index_name)
  - constraint: index_type in ('GSI','LSI')
  - constraint: range_key_name is null <=> range_key_type is null
- `ddb_items.json` — Logical item storage for tables. Stores the raw attribute document plus denormalized primary key values for fast get/query/scan. Serves put_item, get_item, update_item, query_table, scan_table. (18 rows; fields: ['item_id', 'table_id', 'pk_s', 'pk_n', 'pk_b', 'sk_s', 'sk_n', 'sk_b', 'attributes', 'attributes_sha256', 'status', 'version', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ACTIVE', 'TOMBSTONED']
  - constraint: foreign_key(table_id) references ddb_tables(table_id) on delete cascade
  - constraint: version >= 1
  - constraint: exactly_one_of(pk_s, pk_n, pk_b) is true
  - constraint: at_most_one_of(sk_s, sk_n, sk_b) is true
- `ddb_capacity_changes.json` — Audit log of table/GSI provisioned throughput change requests and their execution status. Serves update_capacity and update_gsi, and supports describe_table showing recent updates. (19 rows; fields: ['change_id', 'table_id', 'index_id', 'target_type', 'requested_billing_mode', 'requested_read_capacity_units', 'requested_write_capacity_units', 'applied_read_capacity_units', 'applied_write_capacity_units', 'requested_by', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['PENDING', 'APPLYING', 'SUCCEEDED', 'FAILED', 'CANCELLED']
  - constraint: foreign_key(table_id) references ddb_tables(table_id) on delete cascade
  - constraint: index_id is null OR foreign_key(index_id) references ddb_indexes(index_id) on delete cascade
  - constraint: target_type='TABLE' => index_id is null
  - constraint: target_type='GSI' => index_id is not null
- `ddb_operation_logs.json` — Request/response and performance log for table and item operations. Supports debugging, audit, and implementing throttling/quotas for query/scan/put/update/get. (20 rows; fields: ['op_id', 'account_id', 'table_id', 'index_id', 'tool_name', 'request', 'response', 'http_status', 'consumed_read_units', 'consumed_write_units', 'duration_ms', 'status', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['SUCCEEDED', 'FAILED']
  - constraint: tool_name in ('create_table','update_capacity','put_item','get_item','query_table','scan_table','describe_table','list_tables','create_gsi','update_gsi','create_lsi','update_item')
  - constraint: consumed_read_units >= 0
  - constraint: consumed_write_units >= 0
  - constraint: duration_ms >= 0

## Business rules enforced by the tools

- create_table must create a ddb_tables row with status=CREATING, then transition to ACTIVE only after schema validation succeeds; on validation failure set status=FAILED with status_message populated.
- list_tables returns ddb_tables filtered by (account_id, region) and excludes status=DELETING unless explicitly requested by internal callers.
- describe_table returns the table plus its indexes (ddb_indexes) and may include the most recent capacity changes (ddb_capacity_changes ordered by created_at desc).
- update_capacity can only be applied when ddb_tables.status=ACTIVE; it must set table status to UPDATING during application and return it to ACTIVE on success, or FAILED on unrecoverable error.
- update_gsi can only target ddb_indexes where index_type='GSI' and status=ACTIVE; LSI capacity is not mutable and must be rejected.
- create_lsi is only allowed while the table is in status=CREATING; after the table becomes ACTIVE, attempts must fail with a validation error.
- create_gsi is allowed when table status is ACTIVE (or UPDATING if implementation supports concurrent changes); it must create ddb_indexes row with status=CREATING and transition to ACTIVE when built.
- When billing_mode='PAY_PER_REQUEST' on a table, both table and GSI read/write capacity fields must remain NULL; update_capacity/update_gsi must reject non-null RCU/WCU requests in this mode.
- put_item must upsert by (table_id, primary key); if an item exists, it replaces attributes entirely, increments version, updates attributes_sha256, and sets status=ACTIVE.
- get_item must locate by (table_id, primary key) and return only if status=ACTIVE; TOMBSTONED items must be treated as not found.
- update_item must perform partial attribute updates against ddb_items.attributes, increment version, and update attributes_sha256; it must fail if the target item does not exist (or if optimistic concurrency is enabled and version precondition fails).
- query_table must only allow key-condition-based access: it must constrain results by table primary key (pk equals) or by a defined index key schema when querying via an index; non-key filters may be applied after key selection.
- scan_table may read across all ACTIVE items for the table; it must support server-side filtering against attributes and must enforce per-request page size and read-unit throttling.
- All mutating operations (create_table/create_gsi/create_lsi/update_capacity/update_gsi/put_item/update_item) must create an operation log entry in ddb_operation_logs with status and consumed units.
- Provisioned throughput throttling: if billing_mode=PROVISIONED, the server must reject or delay requests that would exceed current RCU/WCU; such events must be logged with error_code='ProvisionedThroughputExceededException'.
- Index uniqueness: ddb_indexes.index_name must be unique per table; create_gsi/create_lsi must reject duplicates.
- FK integrity: items and indexes cannot exist without a table; deleting a table (internal) must cascade-delete its items and indexes and mark related capacity changes as CANCELLED if still PENDING/APPLYING.