# Qdrant Vector Search Server — local MCP environment

This backend models a Qdrant-like vector search service with named collections that contain vector points and optional payload metadata. The main workflows are: enumerate collections, fetch a collection's configuration/statistics, and execute a vector similarity query against a collection to return matched points.

Repository: https://github.com/amansingh0311/mcp-qdrant-openai
Homepage: https://smithery.ai/server/@amansingh0311/mcp-qdrant-openai

## Datastore

- `collections.json` — Vector index collections (Qdrant 'collections') with configuration, lifecycle state, and high-level statistics used by list_collections and collection_info. (12 rows; fields: ['id', 'name', 'status', 'vector_size', 'distance_metric', 'replication_factor', 'shard_count', 'on_disk_payload', 'hnsw_config', 'optimizer_config', 'points_count', 'vectors_count', 'segments_count', 'last_optimized_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['creating', 'green', 'optimizing', 'degraded', 'deleting', 'deleted']
  - constraint: unique(name)
  - constraint: vector_size >= 1
  - constraint: replication_factor >= 1
  - constraint: shard_count >= 1
- `points.json` — Vector points stored inside collections. Each point has a user-supplied id, vector(s), and optional payload metadata. (34 rows; fields: ['id', 'collection_id', 'external_point_id', 'status', 'vector', 'payload', 'payload_hash', 'version', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(collection_id, external_point_id)
  - constraint: version >= 1
  - constraint: vector_length(vector) = (select vector_size from collections where collections.id = points.collection_id)
  - constraint: status = 'deleted' implies point is excluded from search results
- `query_requests.json` — Audit log of query executions for query_collection, including request parameters, execution status, and timing/limits. Supports observability and rate limiting/quota enforcement even though the tool surface does not expose params. (37 rows; fields: ['id', 'collection_id', 'status', 'query_vector', 'filter', 'limit', 'offset', 'with_payload', 'with_vector', 'score_threshold', 'request_source', 'error_message', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: limit >= 1 and limit <= 1000
  - constraint: offset >= 0
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: query_vector is null or vector_length(query_vector) = (select vector_size from collections where collections.id = query_requests.collection_id)
- `query_results.json` — Materialized results for each query execution (top-k matches). Enables returning deterministic results and supports debugging/replay. (29 rows; fields: ['id', 'query_request_id', 'point_id', 'rank', 'score', 'returned_payload', 'returned_vector', 'created_at', 'updated_at'])
  - lifecycle `rank`: []
  - constraint: unique(query_request_id, rank)
  - constraint: rank >= 1
  - constraint: score is finite
  - constraint: FK: points.collection_id must equal (select collection_id from query_requests where query_requests.id = query_results.query_request_id)

## Business rules enforced by the tools

- list_collections reads from collections where status != 'deleted' and returns name plus minimal metadata (e.g., status).
- collection_info requires an existing collections.name with status != 'deleted' and returns its config (vector_size, distance_metric, shard_count, replication_factor, hnsw_config, optimizer_config) and cached stats (points_count, vectors_count, segments_count, last_optimized_at).
- query_collection must resolve a target collection (default or configured at deployment); the query must not execute if the collection status is in ('creating','deleting','deleted').
- When executing query_collection, the service must create a query_requests row and transition status queued -> running -> (succeeded|failed|cancelled), recording duration_ms and error_message on failure.
- If query_requests.query_vector is provided, its length must equal collections.vector_size; otherwise the request must fail with status=failed.
- Search results must only include points with points.status='active' and points.collection_id matching the queried collection.
- query_results must be stored with contiguous ranks starting at 1 up to limit (or fewer if not enough matches) and must satisfy unique(query_request_id, rank).
- If with_payload=false then all query_results.returned_payload must be null for that query_request_id; if with_vector=false then all query_results.returned_vector must be null for that query_request_id.
- limit must be enforced within [1,1000] regardless of client defaults; offset must be >= 0.
- Collection points_count/vectors_count cached fields must be updated (eventually consistent is acceptable) when points are inserted or deleted; deleted points must not contribute to points_count.