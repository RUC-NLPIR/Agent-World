# Figma API Integration — local MCP environment

This backend stores a local integration state for accessing the Figma REST API: an encrypted personal access token, cached metadata for teams/projects/files, and cached design system assets (components, component sets, styles). It also stores file-scoped comments created/queried through the integration, including soft-deletes, and tracks cache freshness and pagination cursors for list endpoints.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@ai-zerolab/mcp-figma

## Datastore

- `figma_accounts.json` — Local configuration and security metadata for a user's Figma API access token used by the integration (backing set_api_key/check_api_key). (12 rows; fields: ['id', 'token_ciphertext', 'token_last4', 'token_fingerprint_sha256', 'status', 'last_validated_at', 'validation_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'invalid']
  - constraint: unique(token_fingerprint_sha256)
  - constraint: token_last4 length = 4
  - constraint: status != 'active' implies token may not be used for outbound API calls
- `figma_entities.json` — Cached Figma domain objects (teams, projects, files) and their list-pagination state; supports get_team_projects and get_project_files as well as file lookups by fileKey. (11 rows; fields: ['id', 'entity_type', 'figma_id', 'parent_entity_id', 'name', 'status', 'branch_data_included', 'list_cursor', 'list_page_size', 'fetched_at', 'raw', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(entity_type, figma_id)
  - constraint: entity_type='team' implies parent_entity_id is null
  - constraint: entity_type='project' implies parent_entity_id references a team entity
  - constraint: entity_type='file' implies parent_entity_id references a project entity
- `figma_file_snapshots.json` — Materialized snapshots of file document data and node subsets to serve get_file and get_file_nodes with parameters (version, depth, node_ids, branch_data). (12 rows; fields: ['id', 'file_entity_id', 'file_key', 'version', 'depth', 'branch_data', 'node_ids', 'status', 'payload', 'fetched_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'evicted']
  - constraint: depth is null or (depth >= 1 and depth <= 4)
  - constraint: branch_data in (true,false)
  - constraint: unique(file_key, coalesce(version,''), coalesce(depth,-1), branch_data, coalesce(hash(node_ids),''))
  - constraint: status='fresh' implies (expires_at is null or expires_at > fetched_at)
- `figma_asset_catalog.json` — Cached design system assets: components, component sets, and styles across teams and files; supports get_team_components, get_team_component_sets, get_team_styles, get_file_components, get_file_styles, get_component, get_style. (12 rows; fields: ['id', 'asset_type', 'asset_key', 'team_entity_id', 'file_entity_id', 'file_key', 'name', 'description', 'node_id', 'status', 'fetched_at', 'raw', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'deleted']
  - constraint: unique(asset_type, asset_key)
  - constraint: asset_type in ('component','component_set') implies asset_key is not null
  - constraint: team_entity_id is null or references a team entity
  - constraint: file_entity_id is null or references a file entity
- `figma_comments.json` — Comments for a file, including locally created comments and soft-deletes; supports get_comments, post_comment, delete_comment. (11 rows; fields: ['id', 'file_entity_id', 'file_key', 'figma_comment_id', 'parent_figma_comment_id', 'message', 'client_meta', 'status', 'posted_to_vendor_at', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(file_key, figma_comment_id)
  - constraint: status='deleted' implies deleted_at is not null
  - constraint: parent_figma_comment_id is null or parent_figma_comment_id != figma_comment_id
  - constraint: message length >= 1
- `figma_renders.json` — Render requests and resulting URLs for node images and image fills; supports get_image and get_image_fills with caching and parameter validation. (12 rows; fields: ['id', 'file_entity_id', 'file_key', 'render_type', 'node_ids', 'scale', 'format', 'svg_include_id', 'svg_simplify_stroke', 'use_absolute_bounds', 'status', 'result', 'error', 'requested_at', 'completed_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'complete', 'failed', 'expired']
  - constraint: render_type='node_image' implies node_ids is not null and length(node_ids) >= 1
  - constraint: render_type='image_fills' implies node_ids is null
  - constraint: scale is null or (scale >= 0.01 and scale <= 4)
  - constraint: format is null or format in ('jpg','png','svg','pdf')

## Business rules enforced by the tools

- set_api_key must upsert exactly one figma_accounts row in status='active'; any previously active token must transition to 'revoked' before activating the new token.
- check_api_key returns configured=true iff there exists a figma_accounts row with status='active' and token_ciphertext present.
- get_file(fileKey, version, depth, branch_data) must validate depth in [1,4] when provided; it should return a figma_file_snapshots row matching (file_key, version, depth, branch_data) with status='fresh' when available, otherwise fetch from vendor and create/update a snapshot.
- get_file_nodes(fileKey, node_ids, depth, version) must validate node_ids is a non-empty array and depth in [1,4] when provided; it must store node_ids in figma_file_snapshots for cache keying and reuse.
- get_image(fileKey, ids, scale, format, svg_include_id, svg_simplify_stroke, use_absolute_bounds) must validate ids non-empty, scale within [0.01,4] when provided, and format ∈ {jpg,png,svg,pdf} when provided; it may reuse a figma_renders row in status='complete' that is not expired.
- get_image_fills(fileKey) must create or reuse a figma_renders row with render_type='image_fills' for that file; no node_ids may be stored for this type.
- post_comment(fileKey, message, client_meta, comment_id) must create a figma_comments row in status='active'; on successful vendor creation it must set figma_comment_id and posted_to_vendor_at; comment_id, if provided, maps to parent_figma_comment_id.
- delete_comment(fileKey, comment_id) must mark the matching figma_comments row (by file_key and figma_comment_id=comment_id) as status='deleted' and set deleted_at; repeated deletes must be idempotent.
- get_comments(fileKey) must not return comments with status='deleted' unless explicitly requested internally for reconciliation.
- get_team_projects(team_id, page_size, cursor) and get_project_files(project_id, page_size, cursor, branch_data) must validate page_size when provided is an integer in [1,1000]; cursor is treated as an opaque string and stored on the container entity (team or project) as list_cursor for subsequent paging.
- get_project_files with branch_data=true must record branch_data_included=true on the project entity for that fetch; cached file entities returned from that fetch must also have raw updated accordingly.
- get_team_components/get_team_component_sets/get_team_styles must upsert figma_asset_catalog rows scoped by team_entity_id with unique(asset_type, asset_key); pagination cursor/page_size are stored on the team entity.
- get_file_components/get_file_styles must upsert figma_asset_catalog rows scoped by file_entity_id and file_key; assets removed from the latest vendor response should transition to status='deprecated' (not immediately deleted) unless vendor indicates deletion.
- get_component(key) and get_style(key) must resolve via figma_asset_catalog.asset_key; if missing or stale, the system may fetch from vendor and upsert the asset row.