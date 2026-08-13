# Neo4j Knowledge Graph Memory — local MCP environment

This backend persists a session-scoped, multi-database knowledge graph memory service backed by Neo4j concepts: nodes (memories), observations (append-only insights attached to nodes), and relations (typed edges between nodes). It supports switching the active database context per session, unified retrieval (text/IDs/wildcard) with temporal and graph traversal options, and atomic modification workflows (update/delete/cascade, add observations, create relations) while tracking access analytics.

Repository: https://github.com/sylweriusz/mcp-neo4j-memory-server
Homepage: https://smithery.ai/server/@sylweriusz/mcp-neo4j-memory-server

## Datastore

- `databases.json` — Logical Neo4j database contexts. database_switch selects/creates one and binds it to a session; all memories/observations/relations are scoped to a database. (12 rows; fields: ['id', 'name', 'status', 'created_at', 'updated_at', 'archived_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(name)
  - constraint: name length between 1 and 128
  - constraint: status in ('active','archived','deleted')
  - constraint: archived_at is not null iff status='archived'
- `sessions.json` — Session-scoped context binding for database_switch. Subsequent memory_find/memory_modify calls resolve the active database via the session's current_database_id. (18 rows; fields: ['id', 'current_database_id', 'status', 'last_activity_at', 'created_at', 'updated_at', 'closed_at', 'expires_at'])
  - lifecycle `status`: ['open', 'closed', 'expired']
  - constraint: foreign key (current_database_id) references databases(id) on update restrict on delete restrict
  - constraint: status='open' implies closed_at is null
  - constraint: status in ('open','closed','expired')
- `memories.json` — Knowledge graph nodes ("memories"). Supports text retrieval, ID lookup, wildcard listing, temporal filters (createdAfter), updates/deletes (including cascade), and access timestamp analytics. (18 rows; fields: ['id', 'database_id', 'title', 'content', 'properties', 'tags', 'status', 'created_at', 'updated_at', 'last_accessed_at', 'access_count', 'deleted_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key (database_id) references databases(id) on update restrict on delete restrict
  - constraint: content length between 1 and 200000
  - constraint: access_count >= 0
  - constraint: deleted_at is not null iff status='deleted'
- `observations.json` — Append-only insights attached to a memory. memory_modify add-observations inserts new rows; used to reconstruct "full" context responses and to encourage substantial, session-level additions. (18 rows; fields: ['id', 'database_id', 'memory_id', 'text', 'source', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key (memory_id) references memories(id) on update restrict on delete restrict
  - constraint: foreign key (database_id) references databases(id) on update restrict on delete restrict
  - constraint: text length between 1 and 50000
  - constraint: deleted_at is not null iff status='deleted'
- `relations.json` — Typed edges between memories. memory_modify create-relations inserts edges; memory_find relations-only / traverseFrom queries read and traverse these edges with depth constraints. Deleting a memory cascades by deleting related edges. (19 rows; fields: ['id', 'database_id', 'from_memory_id', 'to_memory_id', 'relation_type', 'properties', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key (from_memory_id) references memories(id) on update restrict on delete restrict
  - constraint: foreign key (to_memory_id) references memories(id) on update restrict on delete restrict
  - constraint: foreign key (database_id) references databases(id) on update restrict on delete restrict
  - constraint: from_memory_id <> to_memory_id

## Business rules enforced by the tools

- database_switch(session_id, database_name) must upsert a row in databases by unique(name) with status='active' (unless previously deleted, which must be rejected), and then set sessions.current_database_id accordingly; if the session does not exist, create it with status='open'.
- All operations in memory_find and memory_modify must resolve the active database by sessions.current_database_id and must only read/write rows whose database_id matches that database.
- memory_find must support three query modes: (1) IDs array -> fetch matching memories by id within the active database; (2) text -> search over memories.content/title/tags and optionally observations.text within the active database; (3) '*' -> list memories within the active database (bounded and ordered).
- memory_find createdAfter must accept either an ISO date/time string or a duration like '7d'/'24h' and filter memories.created_at > computed_timestamp.
- memory_find context must support: minimal (return memory id/title plus small excerpts and counts), full (include memory.properties, all active observations ordered by created_at, and optionally relations), and relations-only (return only nodes/edges for the matched set/traversal).
- memory_find graph traversal must accept traverseFrom (a memory id), relations (allowed relation_type list or wildcard), and depth (integer 1..5). Traversal must only follow active relations within the active database.
- memory_find must update analytics for each returned memory: set last_accessed_at=now and increment access_count atomically.
- memory_modify must execute atomically: if any referenced memory_id does not exist (status='active') in the active database, the entire operation fails with no partial writes.
- memory_modify update must only mutate memories.properties/title/content/tags and set updated_at=now; it must not directly edit historical observations (use add-observations instead).
- memory_modify add-observations must insert one or more observations rows with status='active' and created_at=now; each observation.text must be non-empty and should be rate-limited to prevent fragments (enforced as: max 20 observations per session per hour).
- memory_modify create-relations must only link existing active memories in the same database and must enforce unique(database_id, from_memory_id, to_memory_id, relation_type) for active relations.
- memory_modify delete must soft-delete the memory (status='deleted', deleted_at=now) and must cascade soft-deletes to all observations and relations where memory_id=deleted memory or from/to references it; cascade must be part of the same transaction.
- No reads should return rows with status='deleted' unless an internal/debug flag is enabled (not exposed by the tool surface).
- Archived databases are read-only: memory_modify must be rejected when sessions.current_database_id references a databases row with status='archived' or 'deleted'.