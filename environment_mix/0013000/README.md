# Qdrant Server — local MCP environment

This backend stores vector "memories" and supports inserting them into a Qdrant-like store and searching/retrieving them later. The main workflows are: (1) write/upsert memories into a collection, (2) run similarity searches to find relevant memories, and (3) track API usage and operational status for reliability and quota enforcement.

Repository: https://github.com/qdrant/mcp-server-qdrant
Homepage: https://smithery.ai/server/mcp-server-qdrant

## Datastore

- `workspaces.json` — Tenant boundary for memory storage and search. A workspace owns collections, points, API keys, and usage accounting. (18 rows; fields: ['id', 'name', 'status', 'default_collection_id', 'retention_days', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: retention_days IS NULL OR retention_days >= 1
- `api_keys.json` — API keys granting access to a workspace. Used by qdrant-store and qdrant-find for authentication/authorization and quota attribution. (18 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'status', 'scopes', 'rate_limit_rpm', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: rate_limit_rpm IS NULL OR rate_limit_rpm >= 1
- `vector_collections.json` — Logical Qdrant collections within a workspace. Points are stored and searched within a collection. (18 rows; fields: ['id', 'workspace_id', 'name', 'status', 'vector_size', 'distance', 'default_top_k', 'payload_schema', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'rebuilding', 'deleted']
  - constraint: unique(workspace_id, name)
  - constraint: vector_size >= 2 AND vector_size <= 65536
  - constraint: default_top_k >= 1 AND default_top_k <= 1000
- `memory_points.json` — Stored memories/points: a vector embedding plus associated payload (text, metadata). This is the primary data written by qdrant-store and read/queried by qdrant-find. (20 rows; fields: ['id', 'workspace_id', 'collection_id', 'external_point_id', 'status', 'content_text', 'embedding', 'payload', 'content_hash', 'created_by_api_key_id', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'tombstoned']
  - constraint: foreign key (collection_id) references vector_collections(id) ON DELETE RESTRICT
  - constraint: foreign key (workspace_id) references workspaces(id) ON DELETE RESTRICT
  - constraint: created_by_api_key_id IS NULL OR exists(api_keys.id = created_by_api_key_id)
  - constraint: external_point_id IS NULL OR unique(collection_id, external_point_id)
- `search_requests.json` — Audit/log of similarity searches and store operations for observability, throttling, and debugging. Used by qdrant-find (and optionally qdrant-store) to record inputs and outputs summaries. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'tool_name', 'status', 'collection_id', 'input', 'result_count', 'latency_ms', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'succeeded', 'failed', 'rate_limited']
  - constraint: latency_ms IS NULL OR latency_ms >= 0
  - constraint: result_count IS NULL OR result_count >= 0

## Business rules enforced by the tools

- qdrant-store must insert or upsert one or more memory_points; if an external_point_id is provided and exists within the same collection_id, the existing row is updated (embedding/content_text/payload) and updated_at is refreshed.
- qdrant-store must reject inserts where json_array_length(embedding) != vector_collections.vector_size for the target collection.
- qdrant-find must search only within a single resolved collection_id (explicitly specified by server defaults or workspace.default_collection_id); it returns only memory_points with status = 'active'.
- If workspaces.status != 'active', both qdrant-store and qdrant-find must fail with an authorization/availability error and must not mutate memory_points.
- If api_keys.status != 'active' or missing required scope for the tool (store for qdrant-store, find for qdrant-find), the request must be rejected and logged in search_requests with status = 'failed' or 'rate_limited' as appropriate.
- Rate limiting: if api_keys.rate_limit_rpm is set, requests exceeding the limit within a rolling 60s window must be rejected and logged with search_requests.status = 'rate_limited'.
- A memory_point in status 'tombstoned' must have deleted_at set; transitioning to tombstoned is irreversible.
- workspace.default_collection_id, if set, must reference a vector_collections row with matching workspace_id and status != 'deleted'.
- vector_collections.name must be unique per workspace; memory_points.external_point_id and memory_points.content_hash (when provided) must be unique per collection to support idempotency/deduplication.
- Every tool call should create a search_requests row in status 'received' and must transition it to a terminal state (succeeded/failed/rate_limited) with updated_at set.