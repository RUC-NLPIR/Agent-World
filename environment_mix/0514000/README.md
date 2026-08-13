# Framelink Figma MCP — local MCP environment

This backend stores ingested Figma file metadata and a node graph snapshot so clients can retrieve structured context (frames, components, text, styles) and download rendered assets (SVG/PNG) for specific nodes. Main workflows: (1) ingest/sync a Figma file into a normalized snapshot; (2) request image renders for nodes and track resulting downloadable assets.

Repository: https://github.com/adexdsamson/Figma-Context-MCP
Homepage: https://smithery.ai/server/@adexdsamson/figma-context-mcp

## Datastore

- `figma_files.json` — Represents a connected Figma file that can be synced for contextual data and rendered assets. (18 rows; fields: ['id', 'figma_file_key', 'name', 'team_id', 'project_id', 'last_synced_at', 'last_modified_at_remote', 'status', 'auth_context_id', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'needs_auth', 'error', 'archived']
  - constraint: unique(figma_file_key)
  - constraint: status in ('active','needs_auth','error','archived')
- `figma_file_snapshots.json` — Immutable snapshots of a Figma file at a point in time (document tree + derived context). get_figma_data reads from the most recent 'ready' snapshot. (18 rows; fields: ['id', 'figma_file_id', 'figma_version', 'document_etag', 'raw_document', 'derived_context', 'node_count', 'status', 'build_started_at', 'build_completed_at', 'error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'building', 'ready', 'failed']
  - constraint: fk(figma_file_id) references figma_files(id) on delete cascade
  - constraint: node_count >= 0
  - constraint: unique(figma_file_id, document_etag) where document_etag is not null
- `figma_nodes.json` — Normalized node records for a given snapshot (frames, groups, components, instances, vectors, images, text, etc.). Used to serve context and to locate renderable nodes for image download. (17 rows; fields: ['id', 'snapshot_id', 'figma_node_id', 'parent_figma_node_id', 'node_type', 'name', 'is_visible', 'absolute_bounding_box', 'text_content', 'style', 'component_key', 'renderable', 'created_at', 'updated_at'])
  - lifecycle `node_type`: ['DOCUMENT', 'CANVAS', 'FRAME', 'GROUP', 'SECTION', 'COMPONENT', 'COMPONENT_SET', 'INSTANCE', 'TEXT', 'VECTOR', 'STAR', 'LINE', 'ELLIPSE', 'RECTANGLE', 'POLYGON', 'BOOLEAN_OPERATION', 'SLICE', 'STAMP', 'WASHI_TAPE', 'HIGHLIGHT', 'EMBED', 'LINK_UNFURL', 'WIDGET', 'IMAGE', 'OTHER']
  - constraint: fk(snapshot_id) references figma_file_snapshots(id) on delete cascade
  - constraint: unique(snapshot_id, figma_node_id)
  - constraint: is_visible in (true,false)
  - constraint: renderable in (true,false)
- `figma_image_render_jobs.json` — Tracks requests to render/download SVG/PNG for a set of Figma nodes from a specific snapshot/file. download_figma_images creates jobs; results are stored in figma_rendered_assets. (19 rows; fields: ['id', 'figma_file_id', 'snapshot_id', 'requested_node_ids', 'formats', 'scale', 'use_absolute_bounds', 'status', 'requested_at', 'completed_at', 'error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'partially_succeeded', 'failed', 'cancelled']
  - constraint: fk(figma_file_id) references figma_files(id) on delete cascade
  - constraint: fk(snapshot_id) references figma_file_snapshots(id) on delete set null
  - constraint: array_length(requested_node_ids) between 1 and 500
  - constraint: formats subset_of ['svg','png'] and array_length(formats) between 1 and 2
- `figma_rendered_assets.json` — Rendered asset outputs per node and format, produced by a render job. Stores storage pointers and download URLs/expiry. (20 rows; fields: ['id', 'render_job_id', 'figma_file_id', 'snapshot_id', 'figma_node_id', 'format', 'scale', 'content_type', 'byte_size', 'storage_provider', 'storage_key', 'source_url', 'source_url_expires_at', 'status', 'error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'expired', 'deleted', 'error']
  - constraint: fk(render_job_id) references figma_image_render_jobs(id) on delete cascade
  - constraint: fk(figma_file_id) references figma_files(id) on delete cascade
  - constraint: fk(snapshot_id) references figma_file_snapshots(id) on delete set null
  - constraint: unique(render_job_id, figma_node_id, format, coalesce(scale, 0))

## Business rules enforced by the tools

- get_figma_data must return context from the most recent figma_file_snapshots row with status='ready' for a given figma_files.figma_file_key; if none exists, the service must create a new snapshot (status='queued') and eventually transition it through building->ready or building->failed.
- A figma_file_snapshots row may only transition status according to figma_file_snapshots.lifecycle.transitions; direct transitions (e.g., queued->ready) are rejected.
- When building a snapshot, every node from the upstream Figma document must produce exactly one figma_nodes row keyed by (snapshot_id, figma_node_id).
- download_figma_images must create a figma_image_render_jobs row with requested_node_ids length between 1 and 500; otherwise reject the request.
- download_figma_images must only attempt renders for nodes that are renderable=true and is_visible=true in the referenced snapshot when snapshot_id is provided; non-renderable nodes must be marked as asset status='error' with a reason, and the job may end as partially_succeeded.
- For each (render_job_id, figma_node_id, format, scale) combination, at most one figma_rendered_assets row may exist; concurrent requests must upsert or de-duplicate to preserve uniqueness.
- If a figma_files row is status='needs_auth', both tools must fail with an authorization error and must not create new snapshots or render jobs until status returns to 'active'.
- Rendered assets with a source_url_expires_at in the past must be transitioned to status='expired' by background maintenance; expired assets may be re-rendered by creating a new render job.
- Deleting/archiving a figma_files row (status='archived') must prevent creation of new snapshots and render jobs; existing snapshots/assets remain readable unless separately deleted.
- Foreign key integrity must be enforced: no snapshot, node, render job, or asset can reference a non-existent parent id.