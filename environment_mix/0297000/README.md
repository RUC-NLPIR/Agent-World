# Aindreyway Codex Keeper — local MCP environment

Codex Keeper stores a catalog of documentation sources (name/url/category/tags/version) and maintains a locally searchable content index for each source. Core workflows are: add/list/remove sources, run update jobs to fetch and re-index content, and execute searches with optional category/tag filters over the indexed documents.

Repository: https://github.com/aindreyway/mcp-codex-keeper
Homepage: https://smithery.ai/server/@aindreyway/mcp-codex-keeper

## Datastore

- `documentation_sources.json` — Top-level registry of documentation sources that users can add, list, update, search, and remove by name. (18 rows; fields: ['id', 'name', 'url', 'description', 'category', 'version', 'status', 'last_updated_at', 'update_cooldown_seconds', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removing', 'removed', 'error']
  - constraint: unique(name)
  - constraint: unique(url)
  - constraint: length(name) between 1 and 200
  - constraint: length(category) between 1 and 100
- `documentation_tags.json` — Normalized tags for documentation sources; supports filtering by single tag and avoids duplication. (30 rows; fields: ['id', 'tag', 'created_at', 'updated_at'])
  - constraint: unique(tag)
  - constraint: length(tag) between 1 and 64
- `documentation_source_tags.json` — Join table mapping documentation sources to tags. Used by list_documentation and search_documentation tag filtering. (31 rows; fields: ['id', 'source_id', 'tag_id', 'created_at', 'updated_at'])
  - constraint: unique(source_id, tag_id)
  - constraint: fk(source_id) references documentation_sources(id) on delete cascade
  - constraint: fk(tag_id) references documentation_tags(id) on delete restrict
- `documentation_update_jobs.json` — Tracks background update operations (fetch/parse/index) for a documentation source, including forced updates. (32 rows; fields: ['id', 'source_id', 'requested_by', 'force', 'status', 'started_at', 'finished_at', 'error_message', 'fetched_url', 'http_status', 'documents_indexed', 'bytes_indexed', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(source_id) references documentation_sources(id) on delete cascade
  - constraint: documents_indexed >= 0
  - constraint: bytes_indexed >= 0
  - constraint: http_status is null or (http_status between 100 and 599)
- `documentation_documents.json` — Searchable indexed content derived from documentation sources. Stores per-page or per-chunk text and minimal metadata for filtering and ranking. (38 rows; fields: ['id', 'source_id', 'update_job_id', 'canonical_url', 'title', 'content_text', 'content_hash', 'language', 'chunk_index', 'status', 'indexed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'deleted']
  - constraint: fk(source_id) references documentation_sources(id) on delete cascade
  - constraint: fk(update_job_id) references documentation_update_jobs(id) on delete set null
  - constraint: unique(source_id, canonical_url, chunk_index)
  - constraint: chunk_index >= 0

## Business rules enforced by the tools

- list_documentation(category, tag) returns documentation_sources where status='active' and, if category is provided, documentation_sources.category = category, and if tag is provided, the source has a join in documentation_source_tags -> documentation_tags.tag = tag.
- add_documentation requires name, url, category; it creates documentation_sources(status='active') and upserts documentation_tags + documentation_source_tags for each provided tag; name and url must be globally unique (case-insensitive comparison recommended).
- update_documentation(name, force=false) resolves documentation_sources by unique name and requires source.status in ('active','error'); it enqueues a documentation_update_jobs row with force flag and status='queued'.
- update_documentation with force=false must reject or no-op if now() - documentation_sources.last_updated_at < documentation_sources.update_cooldown_seconds; with force=true it may enqueue regardless of cooldown.
- At most one documentation_update_jobs per source may be in status in ('queued','running') at a time; attempts to enqueue another must fail with a conflict or deduplicate to the existing job.
- When a documentation_update_jobs transitions to 'succeeded', documentation_sources.last_updated_at is set to job.finished_at, and newly produced documentation_documents are set to status='active' with indexed_at=finished_at; previously active documents for that source not present in the new index must transition to status='stale' (or 'deleted' depending on retention policy).
- search_documentation(query, category, tag) searches over documentation_documents where status='active' and joins to documentation_sources(status='active'); category/tag filters apply to documentation_sources.category and documentation_tags.tag respectively.
- remove_documentation(name) resolves documentation_sources by name and transitions its status to 'removing' then 'removed'; all documentation_documents for that source must be deleted or marked status='deleted', and any queued/running jobs must be cancelled before final removal.
- All tools that accept 'name' must treat it as the authoritative identifier; if multiple sources would match due to case differences, the backend must prevent that via a uniqueness constraint and normalization on write.
- Numeric fields must remain in valid ranges: update_cooldown_seconds in [0, 2592000], documents_indexed >= 0, bytes_indexed >= 0, http_status null or 100..599.