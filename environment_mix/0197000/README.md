# The Verge News Server — local MCP environment

This backend stores ingested The Verge articles and the crawl/ingestion runs that fetched them, plus a lightweight search log for keyword lookups. Main workflows: scheduled crawls ingest new articles into a canonical articles store, and read-only API tools query recent articles (daily/weekly) or perform keyword search over a bounded lookback window.

Repository: https://github.com/manimohans/verge-news-mcp
Homepage: https://smithery.ai/server/@manimohans/verge-news-mcp

## Datastore

- `sources.json` — Content sources that the server ingests from (e.g., The Verge RSS feeds, sections, or API endpoints). Kept extensible in case multiple feeds/sections are used. (12 rows; fields: ['id', 'name', 'base_url', 'feed_url', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(name)
  - constraint: unique(feed_url) where feed_url is not null
  - constraint: base_url must be a valid URL
  - constraint: feed_url must be a valid URL when not null
- `crawl_runs.json` — Tracks ingestion/crawl executions that fetch and parse articles for a given source. Used for monitoring freshness and diagnosing missing items. (18 rows; fields: ['id', 'source_id', 'run_type', 'status', 'started_at', 'finished_at', 'lookback_days', 'fetched_count', 'upserted_count', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(source_id) references sources.id
  - constraint: fetched_count >= 0
  - constraint: upserted_count >= 0
  - constraint: lookback_days is null or (lookback_days >= 1 and lookback_days <= 3650)
- `articles.json` — Canonical store of The Verge articles used to serve daily/weekly listing and keyword search. Articles are upserted by normalized URL and can be updated when upstream metadata changes. (20 rows; fields: ['id', 'source_id', 'last_crawl_run_id', 'url', 'url_hash', 'title', 'author_names', 'section', 'summary', 'content_text', 'published_at', 'indexed_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suppressed', 'deleted']
  - constraint: foreign key(source_id) references sources.id
  - constraint: foreign key(last_crawl_run_id) references crawl_runs.id
  - constraint: unique(url_hash)
  - constraint: url must be a valid URL
- `search_requests.json` — Audit log of keyword searches performed against stored articles, including the lookback window requested by the client and basic result metrics. Supports monitoring and rate limiting if needed. (18 rows; fields: ['id', 'keyword', 'days', 'requested_start_at', 'requested_end_at', 'status', 'result_count', 'rejection_reason', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'fulfilled', 'rejected']
  - constraint: keyword length between 1 and 200
  - constraint: days >= 1 and days <= 365 (server-enforced cap)
  - constraint: result_count is not null when status='fulfilled'
  - constraint: rejection_reason is not null when status='rejected'

## Business rules enforced by the tools

- Tool get-daily-news returns articles where status='active' and published_at >= (now() at UTC) - interval '1 day', ordered by published_at desc.
- Tool get-weekly-news returns articles where status='active' and published_at >= (now() at UTC) - interval '7 days', ordered by published_at desc.
- Tool search-news requires keyword to be a non-empty string after trimming; otherwise a search_requests row is stored with status='rejected' and rejection_reason='empty_keyword'.
- Tool search-news defaults days to 30 when omitted; if provided, days must be between 1 and 365 inclusive; otherwise store search_requests with status='rejected' and rejection_reason='invalid_days'.
- Tool search-news searches over articles with status='active' and published_at between requested_start_at and requested_end_at, matching keyword against title, summary, and content_text (case-insensitive).
- Articles are upserted by url_hash; a new crawl run may update title/summary/content_text/published_at and must set last_crawl_run_id to the run performing the upsert.
- When a crawl_runs row transitions to status='failed', error_message must be populated and finished_at set; when it transitions to status='succeeded', finished_at must be set and fetched_count/upserted_count must be consistent with ingestion outputs (non-negative integers).
- sources with status='disabled' must not be used for scheduled crawl_runs creation.
- Only articles with indexed_at not null are eligible to be returned from any tool.