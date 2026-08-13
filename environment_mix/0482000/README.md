# Cointelegraph News — local MCP environment

This backend stores Cointelegraph RSS categories, the articles fetched from those feeds, and a request log of tool invocations. The main workflow is: list available categories, fetch and normalize the latest RSS items into stored articles, and serve responses with optional limits and summary truncation.

Repository: https://github.com/kukapay/cointelegraph-mcp
Homepage: https://smithery.ai/server/@kukapay/cointelegraph-mcp

## Datastore

- `rss_categories.json` — Canonical set of supported Cointelegraph RSS categories exposed by the service, including the mapping to RSS feed URLs. (18 rows; fields: ['id', 'slug', 'display_name', 'rss_url', 'sort_order', 'is_active', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: unique(slug)
  - constraint: rss_url != ''
  - constraint: sort_order >= 0
  - constraint: is_active = true implies status in ('active','deprecated')
- `articles.json` — Normalized news articles ingested from Cointelegraph RSS feeds; de-duplicated by canonical URL / GUID. (38 rows; fields: ['id', 'primary_category_id', 'guid', 'canonical_url', 'title', 'author', 'summary', 'content_html', 'image_url', 'published_at', 'language', 'source', 'status', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed', 'tombstoned']
  - constraint: foreign_key(primary_category_id) references rss_categories(id)
  - constraint: unique(canonical_url)
  - constraint: guid is null or unique(guid)
  - constraint: published_at <= fetched_at
- `article_categories.json` — Join table mapping an article to multiple categories (e.g., items appearing in multiple feeds). (30 rows; fields: ['id', 'article_id', 'category_id', 'is_primary', 'created_at', 'updated_at'])
  - constraint: foreign_key(article_id) references articles(id) on delete cascade
  - constraint: foreign_key(category_id) references rss_categories(id)
  - constraint: unique(article_id, category_id)
  - constraint: at_most_one_true(is_primary) per article_id
- `rss_fetch_runs.json` — Operational log of RSS fetch executions per category, used for caching, diagnostics, and incremental updates. (35 rows; fields: ['id', 'category_id', 'requested_max_results', 'requested_max_summary_length', 'etag', 'last_modified', 'http_status', 'item_count_fetched', 'item_count_upserted', 'error_message', 'status', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: foreign_key(category_id) references rss_categories(id)
  - constraint: requested_max_results >= -1
  - constraint: requested_max_summary_length >= 0 and requested_max_summary_length <= 5000
  - constraint: item_count_fetched >= 0

## Business rules enforced by the tools

- get_rss_categories returns rss_categories where is_active=true ordered by sort_order ascending, formatted as newline-separated display_name or slug (implementation choice must be consistent).
- get_latest_news.category must match an active rss_categories.slug; if 'all' is provided, the service fetches/serves from a designated 'all' category row rather than attempting to union every category unless explicitly implemented.
- get_latest_news.max_results = -1 means 'no explicit limit' but the backend must enforce a hard safety cap per request (e.g., <= 200 items) to prevent unbounded responses; the applied cap must be recorded in rss_fetch_runs.requested_max_results as provided and optionally in logs/metrics.
- get_latest_news.max_summary_length must be >= 0; summaries returned to callers are truncated to at most max_summary_length characters without modifying stored articles.summary (presentation-layer truncation).
- Each successful get_latest_news invocation records an rss_fetch_runs row with status succeeded/failed and populates item_count_fetched and item_count_upserted; failures must store error_message and status=failed.
- Articles are upserted on canonical_url (and optionally guid when present); canonical_url must remain globally unique across articles.
- If an article appears in multiple category feeds, article_categories maintains unique(article_id, category_id) and ensures exactly one is_primary=true per article (matching articles.primary_category_id).
- An rss_categories row in status=disabled must not be returned by get_rss_categories and must be rejected by get_latest_news.