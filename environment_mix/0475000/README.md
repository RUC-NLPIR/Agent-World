# Wikipedia Information Server — local MCP environment

This backend powers a Wikipedia information API that lets clients search Wikipedia, fetch full articles, fetch summaries, and discover related topics. It stores cached article snapshots, a searchable index of titles/keywords, and per-request logs to support rate limiting, analytics, and cache invalidation workflows.

Repository: https://github.com/Rudra-ravi/wikipedia-mcp
Homepage: https://smithery.ai/server/@Rudra-ravi/wikipedia-mcp

## Datastore

- `api_clients.json` — Registered API clients (or anonymous client fingerprints) used for rate limiting, abuse prevention, and usage analytics. (12 rows; fields: ['id', 'api_key_hash', 'display_name', 'status', 'rate_limit_per_minute', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(api_key_hash) where api_key_hash is not null
  - constraint: rate_limit_per_minute >= 1 and rate_limit_per_minute <= 6000
- `articles.json` — Canonical Wikipedia article records with cached content/summary and metadata. Serves get_article/get_summary and provides base data for related topics. (18 rows; fields: ['id', 'language_code', 'page_id', 'title', 'normalized_title', 'wikipedia_url', 'extract_html', 'extract_text', 'summary_text', 'content_revision_id', 'content_fetched_at', 'summary_fetched_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'missing', 'redirect', 'deleted', 'error']
  - constraint: unique(language_code, page_id)
  - constraint: unique(language_code, normalized_title)
  - constraint: page_id > 0
  - constraint: length(language_code) between 2 and 12
- `article_graph.json` — Directed graph edges representing links and category relationships between articles. Used to compute related topics based on links/categories. (18 rows; fields: ['id', 'language_code', 'from_article_id', 'to_article_id', 'edge_type', 'weight', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'disabled']
  - constraint: foreign key(from_article_id) references articles(id) on delete cascade
  - constraint: foreign key(to_article_id) references articles(id) on delete cascade
  - constraint: from_article_id <> to_article_id
  - constraint: unique(language_code, from_article_id, to_article_id, edge_type)
- `search_index.json` — Searchable index rows for Wikipedia titles and key terms. Supports search_wikipedia with fast lookups over cached data. (18 rows; fields: ['id', 'language_code', 'article_id', 'title', 'normalized_title', 'keywords', 'popularity_score', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'disabled']
  - constraint: foreign key(article_id) references articles(id) on delete cascade
  - constraint: unique(language_code, article_id)
  - constraint: popularity_score >= 0 and popularity_score <= 1e9
  - constraint: keywords is not null
- `request_logs.json` — Immutable per-tool request log for observability, rate limiting, and debugging. Captures the tool invoked and the effective article/search inputs (even though the public tool schema shows no parameters). (18 rows; fields: ['id', 'client_id', 'tool_name', 'input', 'matched_article_id', 'http_status', 'cache_hit', 'latency_ms', 'error_code', 'created_at', 'updated_at'])
  - lifecycle `http_status`: ['200', '400', '404', '429', '500', '502', '503']
  - constraint: foreign key(client_id) references api_clients(id) on delete set null
  - constraint: foreign key(matched_article_id) references articles(id) on delete set null
  - constraint: http_status >= 100 and http_status <= 599
  - constraint: latency_ms >= 0 and latency_ms <= 600000

## Business rules enforced by the tools

- search_wikipedia reads from search_index where status='active' and language_code defaults to 'en' when not provided in the effective input; results must reference articles with status in ('active','redirect') only.
- get_article resolves an article by (language_code, normalized_title) or (language_code, page_id); if multiple matches exist due to bad data, the request must fail with http_status=500 and log error_code='DATA_INTEGRITY_VIOLATION'.
- get_summary uses articles.summary_text when summary_fetched_at is within the configured TTL; otherwise it refreshes from Wikipedia and updates summary_text, summary_fetched_at, updated_at, and content_revision_id when available.
- get_article uses articles.extract_html/extract_text when content_fetched_at is within the configured TTL; otherwise it refreshes from Wikipedia and updates extract fields and content_fetched_at.
- get_related_topics computes candidates by traversing article_graph edges from the resolved article where edge_type in ('link','category') and status='active', then ranks by (sum(weight), popularity_score) and excludes the source article itself.
- Any request exceeding the caller's rate_limit_per_minute must return http_status=429 and still insert a request_logs row with cache_hit=false and error_code='RATE_LIMITED'.
- Writes are limited to cache and index maintenance: only articles, search_index, article_graph may be updated by background refresh; request_logs are append-only (no updates except updated_at mirroring created_at).
- articles.status='deleted' or 'missing' must cause get_article/get_summary/get_related_topics to return http_status=404 and log matched_article_id when a lookup was attempted.
- Foreign key integrity must be enforced such that no search_index or article_graph row can reference a non-existent articles.id.
- Status transitions for articles, search_index, and article_graph must follow the declared lifecycle transitions; direct transitions not listed must be rejected.