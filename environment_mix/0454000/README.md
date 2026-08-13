# Hugging Face MCP Server — local MCP environment

This backend powers an MCP server that searches and fetches detailed metadata about Hugging Face Hub resources (models, datasets, spaces), plus papers and curated daily paper lists, and Hub collections. It stores normalized snapshots of Hub entities and logs each tool call (queries + results) to support caching, rate limiting, and reproducibility of responses.

Repository: https://github.com/shreyaskarnik/huggingface-mcp-server
Homepage: https://smithery.ai/server/@shreyaskarnik/huggingface-mcp-server

## Datastore

- `hf_requests.json` — Audit/log of every MCP tool invocation, its parameters, execution status, and timing. Used for debugging, caching decisions, and enforcing per-client quotas. (34 rows; fields: ['id', 'tool_name', 'client_id', 'request_params', 'normalized_cache_key', 'status', 'http_status_code', 'error_message', 'result_count', 'started_at', 'finished_at', 'cache_hit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: tool_name in allowed enum
  - constraint: normalized_cache_key is required
  - constraint: cache_hit must be false when status in ('queued','running')
  - constraint: finished_at >= started_at when both non-null
- `hub_entities.json` — Canonical snapshot of Hugging Face Hub resources (models, datasets, spaces). Supports both search and get-info tools via type + repo_id lookups and lightweight cached metadata. (32 rows; fields: ['id', 'entity_type', 'repo_id', 'author', 'name', 'description', 'tags', 'sdk', 'downloads', 'likes', 'last_modified_at', 'card_data', 'status', 'refreshed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'deleted']
  - constraint: unique(entity_type, repo_id)
  - constraint: tags must be an array (possibly empty) of non-empty strings
  - constraint: sdk must be null unless entity_type='space'
  - constraint: downloads >= 0 when non-null
- `papers.json` — Metadata for papers referenced by Hugging Face papers endpoints and arXiv IDs, including daily curated lists. (20 rows; fields: ['id', 'arxiv_id', 'title', 'authors', 'abstract', 'published_at', 'pdf_url', 'upstream_url', 'hf_metadata', 'status', 'refreshed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale']
  - constraint: unique(arxiv_id)
  - constraint: authors must be an array (possibly empty) of non-empty strings
- `daily_paper_editions.json` — Stores Hugging Face 'daily papers' editions by date and their membership, enabling get-daily-papers and caching of curated lists. (12 rows; fields: ['id', 'edition_date', 'status', 'papers', 'refreshed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale']
  - constraint: unique(edition_date)
  - constraint: papers is an array of objects with required fields (paper_id, rank)
  - constraint: each papers[].paper_id must reference papers.id
  - constraint: papers[].rank must be integer >= 1
- `collections.json` — Hugging Face Hub Collections (user/org curated lists) and their items. Supports search-collections and get-collection-info. (12 rows; fields: ['id', 'namespace', 'collection_id', 'owner', 'title', 'description', 'items', 'status', 'refreshed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'deleted']
  - constraint: unique(namespace, collection_id)
  - constraint: owner is required (non-empty)
  - constraint: items is an array of objects with required fields (item_path)
  - constraint: if items[].hub_entity_id is non-null it must reference hub_entities.id

## Business rules enforced by the tools

- For search-models/search-datasets/search-spaces/search-collections: if limit is provided it must be an integer between 1 and 100; otherwise default to 20.
- For search-* tools: query/author/tags/sdk/owner/item are optional filters; when present they must be trimmed and must not exceed 256 characters each.
- For search-models/search-datasets/search-spaces: tags tool parameter is treated as a filter string; implementation must support either exact match against hub_entities.tags elements or tokenized match; the chosen behavior must be consistent and reflected in normalized_cache_key generation.
- get-model-info requires model_id and must resolve hub_entities where entity_type='model' and repo_id=model_id; if not found or stale beyond TTL, fetch upstream and upsert.
- get-dataset-info requires dataset_id and must resolve hub_entities where entity_type='dataset' and repo_id=dataset_id; if not found or stale beyond TTL, fetch upstream and upsert.
- get-space-info requires space_id and must resolve hub_entities where entity_type='space' and repo_id=space_id; if not found or stale beyond TTL, fetch upstream and upsert.
- get-paper-info requires arxiv_id and must resolve papers.arxiv_id=arxiv_id; if not found or stale beyond TTL, fetch upstream and upsert.
- get-daily-papers returns the most recent active daily_paper_editions ordered by edition_date desc; if newest edition is stale beyond TTL, refresh from upstream before responding.
- search-collections supports filters: owner (collections.owner), item (must match any items[].item_path), query (must match collections.title/description); missing filters return recent active collections ordered by refreshed_at desc.
- All tool invocations must create an hf_requests row with status transitioning queued->running->(succeeded|failed); status must never move from failed/succeeded back to running.
- normalized_cache_key must be unique per (tool_name, normalized_cache_key, client_id) within a short time window enforced at the application layer to dedupe concurrent identical requests.
- Cache TTL rules: hub_entities/papers/collections/daily_paper_editions older than configured TTL must be marked stale on read and refreshed before serving unless upstream is unavailable (in which case stale may be served with cache_hit=true and status remains stale).