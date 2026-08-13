# Met Museum Server — local MCP environment

This backend caches and serves read-only data from the Metropolitan Museum of Art Collection API, including departments, object records, and associated images. Core workflows are (1) list departments, (2) search for object IDs by query with optional filters, and (3) fetch a single object record and optionally ingest/store its primary image as a server resource.

Repository: https://github.com/mikechao/metmuseum-mcp
Homepage: https://smithery.ai/server/@mikechao/metmuseum-mcp

## Datastore

- `departments.json` — Met Museum departments cached from the upstream API, used to validate and filter searches and to enrich object metadata. (34 rows; fields: ['id', 'met_department_id', 'display_name', 'status', 'source', 'source_etag', 'source_last_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: unique(met_department_id)
  - constraint: display_name <> ''
  - constraint: met_department_id > 0
- `museum_objects.json` — Cached Met Museum object records keyed by upstream objectId. Stores core searchable/display fields and links to an optional stored primary image resource. (35 rows; fields: ['id', 'met_object_id', 'department_id', 'title', 'object_name', 'artist_display_name', 'culture', 'period', 'object_date', 'medium', 'dimensions', 'credit_line', 'is_public_domain', 'object_url', 'primary_image_url', 'primary_image_small_url', 'has_images', 'ingested_image_resource_id', 'status', 'source', 'source_last_fetched_at', 'source_raw', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'tombstoned']
  - constraint: unique(met_object_id)
  - constraint: met_object_id > 0
  - constraint: has_images = (primary_image_url is not null or primary_image_small_url is not null)
  - constraint: foreign key (department_id) references departments(id) on update restrict on delete set null
- `search_queries.json` — Audit log and cache of executed searches against the Met API. Stores the input parameters for reproducibility and links to the returned object IDs. (33 rows; fields: ['id', 'q', 'has_images', 'title', 'department_met_id', 'department_id', 'status', 'result_total', 'upstream_request_url', 'error_code', 'error_message', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: q <> ''
  - constraint: result_total is null or result_total >= 0
  - constraint: department_met_id is null or department_met_id > 0
  - constraint: foreign key (department_id) references departments(id) on update restrict on delete set null
- `search_results.json` — Child rows for search_queries storing the ordered list of returned Met object IDs (and optionally linking to cached objects). (33 rows; fields: ['id', 'search_query_id', 'met_object_id', 'museum_object_id', 'rank', 'created_at', 'updated_at'])
  - constraint: foreign key (search_query_id) references search_queries(id) on delete cascade
  - constraint: foreign key (museum_object_id) references museum_objects(id) on delete set null
  - constraint: unique(search_query_id, rank)
  - constraint: unique(search_query_id, met_object_id)
- `resources.json` — Server-managed resources created when returnImage=true for get-museum-object. Stores fetched image blobs/metadata and linkage back to the originating object and upstream URL. (38 rows; fields: ['id', 'resource_type', 'museum_object_id', 'met_object_id', 'source_url', 'content_type', 'byte_size', 'sha256', 'storage_backend', 'storage_key', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'available', 'failed', 'deleted']
  - constraint: source_url <> ''
  - constraint: storage_key <> ''
  - constraint: byte_size is null or byte_size >= 0
  - constraint: met_object_id is null or met_object_id > 0

## Business rules enforced by the tools

- Tool list-departments reads departments where status='active' ordered by met_department_id; if cache is empty or stale, the service may refresh departments from upstream and upsert by met_department_id.
- Tool search-museum-objects must require q (non-empty) and must reject requests where hasImages=true AND title=true.
- Tool search-museum-objects maps departmentId to search_queries.department_met_id and, when possible, resolves to departments.id; if departmentId does not exist in departments, the service must either (a) return a validation error or (b) run upstream search but still store department_met_id with department_id null (pick one behavior and keep it consistent).
- Each call to search-museum-objects creates a search_queries row, transitions status queued->running->(succeeded|failed), and on success inserts search_results rows with rank preserving upstream order; (search_query_id, met_object_id) must be unique.
- Tool get-museum-object must require objectId > 0; it should upsert museum_objects by met_object_id and update source_last_fetched_at on each successful fetch.
- When get-museum-object is called with returnImage=true and the object has a primary image URL, the service must create or reuse a resources row for that (museum_object_id, source_url) and set museum_objects.ingested_image_resource_id to the available resource once download succeeds.
- When returnImage=false, the service must not create a resources row and must not modify museum_objects.ingested_image_resource_id (except possibly clearing it only via an explicit maintenance job, not via this tool).
- FK integrity: search_results.search_query_id must reference an existing search_queries row; deleting a search query cascades its results; deleting a museum object must set referencing search_results.museum_object_id and museum_objects.ingested_image_resource_id to null (or be prevented) to preserve audit history.
- Resource ingestion must enforce deduplication by sha256 when available; if two downloads yield the same sha256, they must point to a single stored blob (or fail the second insert due to unique constraint and reuse the existing row).
- Numeric ranges: met_object_id, met_department_id, rank must be positive integers; result_total must be null or >= 0; byte_size must be null or >= 0.