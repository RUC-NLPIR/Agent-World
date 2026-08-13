# News Feed Server — local MCP environment

This backend stores ingested crypto news flashes and long-form research articles, normalized into a common content model with sources, topics, and ingestion jobs. The main workflows are: scheduled/triggered ingestion from external feeds into items, deduplication and status moderation, and serving the latest published items via the two read-only API tools.

Repository: https://github.com/SpaceStation09/newsFeed-mcp
Homepage: https://smithery.ai/server/@SpaceStation09/newsfeed-mcp

## Datastore

- `sources.json` — Publisher/feed sources used to ingest crypto news flashes and articles (RSS feeds, websites, APIs). Used for attribution, reliability scoring, and de-duplication. (26 rows; fields: ['id', 'name', 'type', 'base_url', 'feed_url', 'reliability_score', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'blocked']
  - constraint: unique(lower(name))
  - constraint: reliability_score >= 0 and reliability_score <= 1
  - constraint: type = 'rss' implies feed_url is not null
  - constraint: status in ('active','disabled','blocked')
- `content_items.json` — Normalized content table containing both short news flashes and long-form articles. This is the primary store queried by getNews and getArticles. (41 rows; fields: ['id', 'content_type', 'source_id', 'source_item_id', 'canonical_url', 'title', 'summary', 'body', 'language', 'published_at', 'ingested_at', 'status', 'duplicate_of_item_id', 'importance_score', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ingested', 'reviewed', 'published', 'suppressed', 'deleted']
  - constraint: foreign key (source_id) references sources(id) on delete restrict
  - constraint: foreign key (duplicate_of_item_id) references content_items(id) on delete set null
  - constraint: content_type in ('news_flash','article')
  - constraint: importance_score >= 0 and importance_score <= 1
- `topics.json` — Controlled vocabulary and tags for crypto content (projects, chains, exchanges, narratives). Enables clustering and future filtering even though current tools return unfiltered latest items. (31 rows; fields: ['id', 'slug', 'display_name', 'category', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated']
  - constraint: unique(lower(slug))
  - constraint: status in ('active','deprecated')
- `content_item_topics.json` — Join table linking content items to topics, with extraction confidence for automated tagging. (31 rows; fields: ['id', 'content_item_id', 'topic_id', 'confidence', 'created_at', 'updated_at'])
  - constraint: foreign key (content_item_id) references content_items(id) on delete cascade
  - constraint: foreign key (topic_id) references topics(id) on delete restrict
  - constraint: unique(content_item_id, topic_id)
  - constraint: confidence >= 0 and confidence <= 1
- `ingestion_jobs.json` — Tracks feed pulls/crawls from sources, capturing status, counts, and error details. Provides operational integrity for keeping getNews/getArticles up-to-date. (32 rows; fields: ['id', 'source_id', 'job_type', 'status', 'started_at', 'finished_at', 'fetched_count', 'inserted_count', 'updated_count', 'deduped_count', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key (source_id) references sources(id) on delete restrict
  - constraint: fetched_count >= 0 and inserted_count >= 0 and updated_count >= 0 and deduped_count >= 0
  - constraint: finished_at is null or started_at is not null
  - constraint: status = 'failed' implies error_message is not null

## Business rules enforced by the tools

- getNews returns a list of content_items where content_type='news_flash' AND status='published' AND duplicate_of_item_id is null, ordered by published_at desc NULLS LAST then ingested_at desc, limited to a server-configured max page size (e.g., 50).
- getArticles returns a list of content_items where content_type='article' AND status='published' AND duplicate_of_item_id is null, ordered by published_at desc NULLS LAST then ingested_at desc, limited to a server-configured max page size (e.g., 50).
- Only sources with status='active' may be ingested; ingestion_jobs for disabled/blocked sources must be rejected.
- A content item may transition to 'published' only if its source is not blocked and it is not marked as a duplicate (duplicate_of_item_id is null).
- Deduplication must enforce at most one canonical item per canonical_url and per (source_id, source_item_id) when those keys exist; duplicates must set duplicate_of_item_id and must not be served by getNews/getArticles.
- importance_score must be set at ingest time (default 0.5) and must remain within [0,1]; ranking logic may incorporate importance_score but must keep chronological ordering stable for equal timestamps.
- If an ingestion_job is marked succeeded/failed/cancelled, finished_at must be set and must be >= started_at.
- Deleting a content_item (status='deleted') must not physically remove rows; join rows in content_item_topics remain but the item must never be returned by getNews/getArticles.