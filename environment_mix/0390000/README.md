# Laravel MCP Companion — local MCP environment

This backend stores a locally-synced cache of official Laravel framework documentation (by version) and supported external Laravel service documentation (Forge/Vapor/Envoyer/Nova, etc.), plus an indexed search layer with query logs. Main workflows are: sync/update docs from upstream sources into versioned documents, browse/list/read documents, and execute full-text searches (with optional context snippets) across framework and external docs; additionally it maintains a small curated package catalog for recommendations, categories, and package details.

Repository: https://github.com/brianirish/laravel-mcp-companion
Homepage: https://smithery.ai/server/@brianirish/laravel-mcp-companion

## Datastore

- `doc_sources.json` — Upstream documentation sources that can be synced and searched (Laravel framework versions and external Laravel services). Drives list_laravel_docs vs list_laravel_services and powers update/sync jobs and search scoping. (18 rows; fields: ['id', 'source_type', 'key', 'display_name', 'repo_url', 'docs_base_url', 'default_branch', 'latest_synced_commit', 'last_synced_at', 'status', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'error']
  - constraint: unique(source_type, key)
  - constraint: source_type='framework' implies docs_base_url is null OR optional; source_type='service' implies key in supported service set enforced at app-level
  - constraint: status='error' implies last_error is not null
- `doc_files.json` — Individual documentation files/pages belonging to a doc source (framework version or external service). Supports listing, reading content, browsing by category, structure extraction, and search indexing metadata. (21 rows; fields: ['id', 'source_id', 'filename', 'category', 'title', 'content_markdown', 'content_sha256', 'sections', 'word_count', 'last_indexed_at', 'status', 'upstream_path', 'upstream_updated_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'stale', 'error']
  - constraint: unique(source_id, filename)
  - constraint: word_count >= 0
  - constraint: content_sha256 matches /^[a-f0-9]{64}$/
  - constraint: status='deleted' implies content_markdown may be retained but excluded from list/search at app-level
- `sync_jobs.json` — Tracks update_laravel_docs and update_external_laravel_docs operations, including force refreshes, selected services/versions, progress and errors. Enables laravel_docs_info and get_laravel_service_info freshness indicators. (18 rows; fields: ['id', 'job_type', 'requested_source_id', 'requested_keys', 'force', 'status', 'started_at', 'finished_at', 'result_summary', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: force in (true,false)
  - constraint: job_type='framework_sync' implies requested_keys is null OR contains framework version keys; job_type='service_sync' implies requested_keys is null OR contains service keys
  - constraint: status in ('queued','running') implies finished_at is null
  - constraint: status in ('succeeded','failed','cancelled') implies finished_at is not null
- `search_queries.json` — Logged searches against cached docs, capturing scope (framework version and/or external services), include_external toggle, and optional context length. Used for analytics, debugging, and potential caching of results. (18 rows; fields: ['id', 'query_text', 'framework_source_id', 'include_external', 'service_source_ids', 'context_length', 'tool_name', 'result_count', 'execution_ms', 'created_at', 'updated_at'])
  - lifecycle `tool_name`: ['search_laravel_docs', 'search_laravel_docs_with_context', 'search_external_laravel_docs']
  - constraint: query_text length between 1 and 2048
  - constraint: execution_ms >= 0
  - constraint: result_count >= 0
  - constraint: context_length is null OR (context_length >= 0 AND context_length <= 5000)
- `packages.json` — Curated Laravel package catalog used for recommendations, categories, and detailed package info/features. Acts as the backend for get_laravel_package_recommendations/get_laravel_package_info/get_laravel_package_categories/get_features_for_laravel_package. (19 rows; fields: ['id', 'package_name', 'display_name', 'category', 'description', 'homepage_url', 'repository_url', 'installation', 'common_use_cases', 'features', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'hidden']
  - constraint: unique(package_name)
  - constraint: package_name matches /^[a-z0-9_.-]+\/[a-z0-9_.-]+$/
  - constraint: category length between 1 and 128

## Business rules enforced by the tools

- list_laravel_docs returns doc_files for doc_sources.source_type='framework' filtered to status='active' doc_files and, when version is provided, scoped to doc_sources.key = version.
- read_laravel_doc_content requires an active doc_sources row (framework) and an active doc_files row matching (source_id, filename); if version is null it resolves the newest active framework source by semantic sort of doc_sources.key (app-level).
- browse_docs_by_category requires category and returns active doc_files for framework sources (optionally scoped by version) where doc_files.category = category.
- get_doc_structure returns doc_files.sections; if sections is null or file is stale, the implementation must (re)parse content_markdown into sections and persist it, updating updated_at and last_indexed_at as appropriate.
- search_laravel_docs searches active framework doc_files content_markdown (and additionally active service doc_files when include_external=true) and writes a search_queries row with tool_name='search_laravel_docs'.
- search_laravel_docs_with_context enforces 0 <= context_length <= 5000; it logs a search_queries row with tool_name='search_laravel_docs_with_context' and stores context_length.
- search_external_laravel_docs searches only active service doc_files; if services is provided it scopes to doc_sources.key IN services; it logs a search_queries row with tool_name='search_external_laravel_docs'.
- list_laravel_services lists active doc_sources where source_type='service'.
- get_laravel_service_info returns doc_sources metadata for a service key, including latest_synced_commit, last_synced_at, status, last_error, and may include latest sync_jobs row for that source as derived info.
- laravel_docs_info returns doc_sources metadata for framework sources; when version is provided it returns the single matching framework source; otherwise it returns all active framework sources with last_synced_at and latest_synced_commit.
- update_laravel_docs creates a sync_jobs row with job_type='framework_sync', force flag, and requested_source_id resolved by version (or null for all framework sources); it transitions status queued->running->(succeeded|failed) and updates doc_sources.last_synced_at/latest_synced_commit on success.
- update_external_laravel_docs creates a sync_jobs row with job_type='service_sync', force flag, and requested_keys/services mapping to doc_sources rows; on success it updates each affected doc_sources.last_synced_at/latest_synced_commit.
- Sync operations are idempotent: a doc_files row is updated only when content_sha256 changes unless force=true; deleted upstream files are marked status='deleted' rather than hard-deleted.
- get_laravel_package_info requires an active or deprecated packages row matching package_name; hidden packages must not be returned.
- get_laravel_package_categories returns active and deprecated packages where category matches exactly (case-insensitive match allowed at app-level); hidden packages excluded.
- get_features_for_laravel_package returns packages.features for the matching package_name; if missing, it returns an empty list.
- get_laravel_package_recommendations performs text matching against packages.common_use_cases/description/category and returns only status='active' packages; it must not create or mutate package rows.