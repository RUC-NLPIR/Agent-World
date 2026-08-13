# Think Tank — local MCP environment

Think Tank stores a local knowledge graph of entities, their observations (facts/memories), and directed relations between entities. It also maintains a lightweight task system synced to the graph, logs structured “thinking” sessions (optionally persisted as memory), and records Exa web search/answer requests and their results for traceability and reuse.

Repository: https://github.com/flight505/mcp-think-tank
Homepage: https://smithery.ai/server/@flight505/mcp-think-tank

## Datastore

- `entities.json` — Canonical nodes in the knowledge graph. Entities are addressed by unique human-readable name and typed by entityType. Soft-deletion is used so dependent observations/relations can be retained for audit or hard-deleted via cascading rules. (18 rows; fields: ['id', 'name', 'entity_type', 'context', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(name)
  - constraint: length(name) >= 1
  - constraint: length(entity_type) >= 1
  - constraint: status = 'deleted' => deleted_at is not null
- `observations.json` — Atomic memory/fact entries attached to an entity. Supports append-only additions, explicit deletions, and rich filtering for memory_query (keyword/date/tag/agent/limit). Also used to persist 'think' output when storeInMemory=true. (17 rows; fields: ['id', 'entity_id', 'content', 'context', 'tags', 'agent', 'source', 'source_ref_id', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(entity_id) references entities(id) on delete restrict
  - constraint: length(content) >= 1
  - constraint: status = 'deleted' => deleted_at is not null
  - constraint: tags elements must be non-empty strings
- `relations.json` — Directed edges between entities. Created/updated/deleted via tools using (from name, to name, relationType) as a natural key. (19 rows; fields: ['id', 'from_entity_id', 'to_entity_id', 'relation_type', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(from_entity_id) references entities(id) on delete cascade
  - constraint: fk(to_entity_id) references entities(id) on delete cascade
  - constraint: length(relation_type) >= 1
  - constraint: from_entity_id <> to_entity_id
- `tasks.json` — Task/todo items produced by plan_tasks and managed via list_tasks/next_task/complete_task/update_tasks. Optionally linked to an entity for syncing with the knowledge graph. (18 rows; fields: ['id', 'title', 'details', 'priority', 'status', 'due_at', 'entity_id', 'source_plan_id', 'started_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['todo', 'in_progress', 'completed', 'cancelled']
  - constraint: length(title) >= 1
  - constraint: priority between 1 and 5
  - constraint: fk(entity_id) references entities(id) on delete set null
  - constraint: status='in_progress' => started_at is not null
- `activity_logs.json` — Append-only operational log for think tool and Exa tool calls. Stores parameters and results for traceability, caching, and debugging. Also supports show_memory_path by storing current active graph file path as a singleton config record (type=system_config). (18 rows; fields: ['id', 'event_type', 'status', 'entity_id', 'category', 'tags', 'context', 'request', 'response', 'memory_path', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['recorded', 'succeeded', 'failed']
  - constraint: event_type='system_config' => memory_path is not null
  - constraint: event_type in ('exa_search','exa_answer') => request is not null
  - constraint: index(event_type, created_at)
  - constraint: index(entity_id, created_at)

## Business rules enforced by the tools

- upsert_entities: For each input entity, if entities.name exists and update=false, do not modify the entity record; only create when absent. If update=true and entity exists, replace entity_type and context with provided values and replace the entity's observations so that after the call, the entity has exactly the provided observations as active (soft-delete prior active observations not present).
- upsert_entities: If entity does not exist, create entities row (status=active) and create one observations row per provided observation string with source='upsert_entities'.
- add_observations: For each entityName, entity must exist and be active; append observations rows (do not deduplicate unless identical content already active for that entity and created by same agent within a short window; if dedup is implemented it must not drop distinct timestamps).
- delete_observations: Only observations matching (entity, content) and status=active may be deleted; deletion is implemented as status='deleted' and deleted_at set.
- create_relations: from/to entity names must exist and be active. Create relation if no active relation exists for (from,to,relationType); otherwise no-op (idempotent).
- update_relations: Relation is identified by (from,to,relationType). If it exists but is deleted, it is reactivated by setting status='active' and clearing deleted_at; if it does not exist, the operation fails validation (or behaves like create depending on implementation, but must be consistent).
- delete_relations: Match by (from,to,relationType) and set status='deleted' with deleted_at; if not found, no-op.
- delete_entities: For each name, set entities.status='deleted' and deleted_at; cascade soft-delete all active relations where from_entity_id or to_entity_id matches. Observations are soft-deleted as well to prevent surfacing deleted entity memory.
- read_graph: Returns all entities with status=active, their active observations, and active relations. Deleted records are excluded unless an internal debug flag is used (not in tool surface).
- search_nodes: Performs case-insensitive search over entities.name and optionally entities.entity_type; returns active entities only.
- open_nodes: Returns entities by name; names that do not exist or are deleted are omitted or reported as not_found, but must not return deleted content.
- memory_query: Filters observations.status='active' and joins entities.status='active'. keyword does substring/full-text match on observations.content; before/after filter observations.created_at; tag filters where tag is in observations.tags; agent matches observations.agent. limit defaults to a safe maximum and is capped (e.g., <= 200) even if a higher number is requested.
- think: Always writes an activity_logs row with event_type='think' and request containing the full parameter set. If storeInMemory=true, it must also create an observations row on the associated entity (or a dedicated 'Think Log' entity created via upsert) with source='think', tags/category/context propagated.
- plan_tasks: Creates one or more tasks rows; each task must have status='todo' initially and a priority within 1..5. If tasks are synced to the knowledge graph, an entity may be created/used to represent the plan, and tasks.entity_id may reference it.
- list_tasks: Returns tasks filtered by status/priority if implemented; default ordering is status (todo/in_progress first), then priority desc, then created_at asc.
- next_task: Selects the highest priority task with status='todo' (tie-break by created_at asc), updates it to status='in_progress' and sets started_at. Operation must be atomic to avoid two callers receiving the same task.
- complete_task: Can only transition a task from in_progress (or todo, if allowed by implementation) to completed; sets completed_at. Completed tasks are immutable except for non-critical metadata updates (e.g., details) if permitted.
- update_tasks: Bulk updates must respect task lifecycle transitions; invalid transitions are rejected for the specific task and must not partially apply without clear per-item results.
- exa_search: Enforces num_results between 1 and 100, type in {auto,keyword,neural}, category and live_crawl enums exactly as specified. Each call is logged to activity_logs with event_type='exa_search'.
- exa_answer: Enforces question length >= 5 and max_citations between 1 and 10. Each call is logged to activity_logs with event_type='exa_answer'.
- show_memory_path: Returns the memory_path from the latest activity_logs row where event_type='system_config' and status='succeeded' (or from a singleton config row); path must be absolute.