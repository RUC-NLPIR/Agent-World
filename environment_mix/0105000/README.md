# Memento — local MCP environment

Memento stores a personal/team knowledge graph consisting of entities (nodes), relations (edges), and observations (fact-like annotations) with time-aware confidence and full version history. The main workflows are creating/updating/deleting graph primitives, searching nodes lexically and semantically via embeddings, and reconstructing the graph at a point in time or with time-decayed confidence for retrieval.

Repository: https://github.com/gannonh/memento-mcp
Homepage: https://smithery.ai/server/@gannonh/memento-mcp

## Datastore

- `entities.json` — Canonical entity (node) records in the knowledge graph. Entities are addressed primarily by name (for open/search) and have lifecycle state plus confidence metadata used by time-decay views. (18 rows; fields: ['id', 'name', 'entity_type', 'summary', 'properties', 'confidence', 'confidence_updated_at', 'deleted_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(lower(name)) where status='active'
  - constraint: confidence >= 0 and confidence <= 1
  - constraint: deleted_at is null when status='active'
  - constraint: deleted_at is not null when status='deleted'
- `observations.json` — Atomic observations attached to entities (facts, notes, claims). Observations are independently versioned via audit log and can be deleted without deleting the entity. (19 rows; fields: ['id', 'entity_id', 'content', 'source', 'observed_at', 'confidence', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(entity_id) references entities(id) on delete cascade
  - constraint: confidence >= 0 and confidence <= 1
  - constraint: deleted_at is null when status='active'
  - constraint: deleted_at is not null when status='deleted'
- `relations.json` — Directed edges between entities with enhanced properties. Relation text should be active voice; stored as a predicate plus optional attributes for reasoning and display. (19 rows; fields: ['id', 'from_entity_id', 'to_entity_id', 'predicate', 'properties', 'confidence', 'confidence_updated_at', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(from_entity_id) references entities(id) on delete cascade
  - constraint: fk(to_entity_id) references entities(id) on delete cascade
  - constraint: from_entity_id <> to_entity_id
  - constraint: predicate <> ''
- `embeddings.json` — Vector embeddings for entities to support semantic_search and debugging/diagnostic tools. Stores model configuration, vector, and generation status for async/forced generation. (19 rows; fields: ['id', 'entity_id', 'model', 'dimensions', 'vector', 'content_hash', 'status', 'last_error', 'generated_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['missing', 'queued', 'generating', 'ready', 'failed']
  - constraint: fk(entity_id) references entities(id) on delete cascade
  - constraint: unique(entity_id, model)
  - constraint: dimensions > 0 and dimensions <= 8192
  - constraint: vector is null when status in ('missing','queued','generating','failed')
- `graph_events.json` — Append-only event log powering entity/relation history and point-in-time graph reconstruction. Each mutating tool writes one or more events, and read tools can materialize 'graph at time' by replaying events up to a timestamp. (19 rows; fields: ['id', 'event_type', 'entity_id', 'relation_id', 'observation_id', 'embedding_id', 'actor', 'payload', 'occurred_at', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['entity.created', 'entity.updated', 'entity.deleted', 'observation.created', 'observation.deleted', 'relation.created', 'relation.updated', 'relation.deleted', 'embedding.queued', 'embedding.generated', 'embedding.failed']
  - constraint: occurred_at <= created_at
  - constraint: at least one of entity_id, relation_id, observation_id, embedding_id must be non-null
  - constraint: payload must include a full snapshot for *.created and *.updated events

## Business rules enforced by the tools

- create_entities upserts entities by name (case-insensitive): if an active entity with the same lower(name) exists, update its properties/summary/entity_type; otherwise create a new entity in status='active'. Each change writes a corresponding graph_events row (entity.created or entity.updated).
- delete_entities sets entities.status='deleted' and deleted_at=now() and must cascade-soft-delete relations (status='deleted') and observations (status='deleted') for those entities, emitting graph_events for each logical deletion.
- create_relations requires from_entity_id and to_entity_id to reference active entities; predicate must be non-empty and stored normalized (trimmed). Duplicate active (from,to,predicate) relations are not allowed; attempts must either be treated as update_relation or rejected.
- update_relation only applies to relations in status='active'; it may change predicate/properties/confidence and must emit relation.updated with a payload containing before/after (or full snapshot).
- delete_relations sets relation.status='deleted' and deleted_at=now() and emits relation.deleted events; hard delete is optional and must not break historical reconstruction.
- add_observations creates observations for existing active entities and sets status='active'; delete_observations sets status='deleted'. Both operations emit observation.* events.
- read_graph returns only status='active' entities/relations/observations by default; any internal admin/debug mode may include deleted records but must be explicit.
- search_nodes performs lexical search over entities.name, entities.summary, and observations.content (active only) using an indexed full-text strategy; results are mapped back to entities.
- open_nodes resolves requested names by case-insensitive match on entities.name where status='active'; unknown names return empty (no implicit create).
- semantic_search uses embeddings where status='ready' and model matches the configured default; if an entity lacks a ready embedding it is excluded unless the implementation triggers background queueing via embeddings.status='queued' and emits embedding.queued.
- get_entity_embedding returns the embeddings row for the entity and default model; if status != 'ready' it must return status and last_error (if any) rather than a vector.
- force_generate_embedding sets (or creates) embeddings(entity_id,model) to status='queued' regardless of current status, updates content_hash, and emits embedding.queued; a worker transitions queued->generating->ready/failed and writes embedding.generated/embedding.failed events.
- debug_embedding_config reads embedding-related configuration from application config, but must also report database readiness using embeddings table presence, default model name, dimensions, and counts by embeddings.status.
- diagnose_vector_search is allowed to bypass application abstractions but must only read from embeddings (and entities for names); it must not mutate graph state.
- get_entity_history and get_relation_history are served exclusively from graph_events filtered by entity_id or relation_id ordered by occurred_at ascending; histories must include deleted events.
- get_graph_at_time(T) reconstructs entities/relations/observations by replaying graph_events with occurred_at <= T, applying events in timestamp order then id order for deterministic ties; deleted status at T excludes items in the returned snapshot.
- get_decayed_graph applies a decay function to confidence for entities/relations/observations based on recency: the base timestamp for decay is max(updated_at, confidence_updated_at, observed_at) where present; confidence must remain clamped to [0,1].
- All writes must keep FK integrity: an active relation cannot point to a deleted entity; deleting an entity must make any related active relations invalid and thus must delete (soft) them in the same transaction.