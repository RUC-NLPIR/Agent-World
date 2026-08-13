# MongoDB MCP Server — local MCP environment

This backend stores MCP server state for connecting to MongoDB instances and executing administrative and CRUD operations against discovered databases/collections. It tracks connection sessions, discovered namespace metadata (databases, collections, indexes), and an auditable operation log for every tool call (including inputs, outcomes, and captured results such as explain plans and server logs).

Repository: https://github.com/mongodb-js/mongodb-mcp-server
Homepage: https://smithery.ai/server/@mongodb-js/mongodb-mcp-server

## Datastore

- `mongo_connections.json` — Represents a configured MongoDB connection target and its active/previous session state, created via the connect tool. Also anchors all subsequent database/collection operations. (12 rows; fields: ['id', 'connection_string', 'connection_string_redacted', 'client_fingerprint', 'topology_type', 'server_version', 'auth_mechanism', 'default_database', 'last_connected_at', 'last_error', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['configured', 'connecting', 'connected', 'failed', 'disconnected']
  - constraint: connection_string must start with 'mongodb://' or 'mongodb+srv://'
  - constraint: unique(client_fingerprint) where client_fingerprint is not null
  - constraint: updated_at >= created_at
- `mongo_databases.json` — Catalog of databases discovered/created/dropped for a specific connection, used to serve list-databases, db-stats, and drop-database, and as a parent for collections. (12 rows; fields: ['id', 'connection_id', 'name', 'status', 'stats', 'stats_refreshed_at', 'discovered_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'dropping', 'dropped', 'unknown']
  - constraint: unique(connection_id, name)
  - constraint: name length between 1 and 64 (MongoDB practical limit; enforce vendor-safe)
  - constraint: FK(connection_id) references mongo_connections(id) on delete cascade
  - constraint: updated_at >= created_at
- `mongo_collections.json` — Catalog of collections for a database and connection, supports list-collections, create-collection, drop-collection, rename-collection, collection-storage-size, collection-schema, and as an anchor for index metadata. (20 rows; fields: ['id', 'connection_id', 'database_id', 'database_name', 'name', 'type', 'status', 'options', 'schema_inference', 'schema_refreshed_at', 'storage_size_bytes', 'storage_size_refreshed_at', 'discovered_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'creating', 'renaming', 'dropping', 'dropped', 'unknown']
  - constraint: unique(connection_id, database_name, name) where status != 'dropped'
  - constraint: FK(connection_id) references mongo_connections(id) on delete cascade
  - constraint: FK(database_id) references mongo_databases(id) on delete cascade
  - constraint: database_name must equal mongo_databases.name for database_id (enforced in application or via trigger)
- `mongo_indexes.json` — Index metadata per collection, serving collection-indexes and create-index. Stores last observed index definitions and allows idempotency checks for create-index. (29 rows; fields: ['id', 'connection_id', 'database_id', 'collection_id', 'database_name', 'collection_name', 'name', 'keys', 'options', 'status', 'last_observed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'creating', 'failed', 'dropped', 'unknown']
  - constraint: unique(collection_id, name) where status != 'dropped'
  - constraint: keys must be a non-empty object
  - constraint: FK(collection_id) references mongo_collections(id) on delete cascade
  - constraint: FK(database_id) references mongo_databases(id) on delete cascade
- `mongo_operations.json` — Immutable audit log of every tool invocation (connect, find, aggregate, write ops, stats, logs, explain, DDL). Stores parameters, derived targets (db/collection), execution timing, and sanitized results for replay/debugging. (37 rows; fields: ['id', 'connection_id', 'tool_name', 'database', 'collection', 'arguments', 'status', 'started_at', 'ended_at', 'duration_ms', 'result', 'result_truncated', 'error', 'read_preference', 'write_concern', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed']
  - constraint: arguments must conform to the JSON schema of tool_name
  - constraint: if tool_name in ('list-databases','mongodb-logs','connect') then database is null or omitted; otherwise database is required
  - constraint: if tool_name in ('list-collections','collection-indexes','create-index','collection-schema','find','insert-many','delete-many','collection-storage-size','count','aggregate','update-many','rename-collection','drop-collection','explain','create-collection') then collection is required (except those that do not specify it: list-collections uses only database; db-stats/drop-database use only database)
  - constraint: duration_ms >= 0

## Business rules enforced by the tools

- connect: Creating or reusing a mongo_connections row requires connectionString to match ^mongodb(\+srv)?:\/\/.+; store encrypted connection_string and store a redacted version in connection_string_redacted.
- All tools except connect and list-databases and mongodb-logs require an existing mongo_connections row with status='connected' (or the call must fail and be logged in mongo_operations with status='failed').
- list-databases: On success, upsert mongo_databases rows for (connection_id, name) and set status='active'; mark discovered_at if newly created.
- list-collections: On success, upsert mongo_collections rows for (connection_id, database_name, name) and set status='active'; populate type/options when available.
- create-collection: Must fail if a non-dropped mongo_collections row already exists for (connection_id, database_name, name) unless the remote server reports it does not exist; on success set/create mongo_databases(status='active') and mongo_collections(status='active').
- drop-collection: Must transition mongo_collections.status from 'active'->'dropping'->'dropped' (or directly to 'dropped' on confirmed success). All mongo_indexes for that collection must transition to 'dropped'.
- rename-collection: Requires source collection status='active'. If dropTarget=false and target exists (non-dropped), operation must fail. If dropTarget=true and target exists, target must be dropped before rename is finalized. Update catalog by setting old name row to 'dropped' (or keeping same id and updating name) and ensuring uniqueness on (connection_id, database_name, name).
- collection-indexes: On success, upsert mongo_indexes for the collection by (collection_id, name), set status='active', and set last_observed_at=now; any previously known indexes not returned may be set to status='unknown' (not 'dropped') unless a drop is confirmed.
- create-index: keys must be a non-empty object. If name is provided, it must be unique within the collection among non-dropped indexes; if not provided, derive/accept server-generated name and persist it. On success set mongo_indexes.status='active'.
- find: arguments.filter/projection/sort are stored verbatim in mongo_operations.arguments; enforce a server-side hard cap on limit to prevent oversized responses; store result documents truncated with result_truncated=true when needed.
- aggregate: arguments.pipeline must be a non-empty array; store pipeline verbatim; store results truncated when needed.
- count: arguments.query is optional; store verbatim; store numeric count result.
- update-many: arguments.update is required; if filter is omitted treat as {}. If upsert is true, record whether an upsert occurred in mongo_operations.result.
- insert-many: documents must be a non-empty array; enforce a maximum documents-per-call (e.g., 1000) and maximum total payload bytes; record insertedCount and insertedIds in mongo_operations.result (sanitized).
- delete-many: if filter is omitted treat as {}; record deletedCount.
- collection-storage-size and db-stats: cache returned stats into mongo_collections.storage_size_bytes or mongo_databases.stats respectively and update *_refreshed_at.
- collection-schema: inferred schema is computed by sampling documents (implementation-defined) and cached into mongo_collections.schema_inference with schema_refreshed_at.
- explain: method must be an array of one or more method objects each with name in {'aggregate','find','count'} and matching arguments schema; store the method array verbatim in mongo_operations.arguments.method and store the explain plan in mongo_operations.result.
- mongodb-logs: type must be 'global' or 'startupWarnings' and limit must be 1..1024; store returned log entries in mongo_operations.result with truncation rules.
- Every tool call must create a mongo_operations row with status transitions received->running->(succeeded|failed), recording started_at/ended_at and duration_ms.