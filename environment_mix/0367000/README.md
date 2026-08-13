# Hacker News — local MCP environment

This backend mirrors core Hacker News entities (users, stories, comments) and supports read/query workflows for listing stories by category, fetching user profiles with recent submissions, searching stories, and retrieving a story thread with comments. It also stores executed search/list requests for caching, observability, and rate-limit accounting.

Repository: https://github.com/erithwik/mcp-hn
Homepage: https://smithery.ai/server/mcp-hn

## Datastore

- `hn_users.json` — Hacker News users (profiles) as synced from the upstream HN API; used to serve get_user_info and to attribute stories/comments. (18 rows; fields: ['id', 'username', 'hn_user_id', 'created_at_hn', 'karma', 'about_html', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'shadow_banned', 'unknown']
  - constraint: unique(username)
  - constraint: karma IS NULL OR karma >= 0
  - constraint: username length between 1 and 64
- `hn_items.json` — HN items: stories and comments in one table (HN's model). Used to serve get_stories, get_story_info, and user submissions. (18 rows; fields: ['id', 'hn_item_id', 'item_type', 'story_subtype', 'title', 'url', 'text_html', 'by_user_id', 'time_posted_at', 'parent_hn_item_id', 'root_story_hn_item_id', 'score_points', 'num_comments', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'dead', 'unknown']
  - constraint: unique(hn_item_id)
  - constraint: item_type in ('story','comment')
  - constraint: item_type='comment' implies parent_hn_item_id IS NOT NULL
  - constraint: item_type='story' implies parent_hn_item_id IS NULL
- `hn_story_feeds.json` — Materialized membership of stories in common feeds (top/new/ask_hn/show_hn) to serve get_stories efficiently and reproducibly over time. (18 rows; fields: ['id', 'feed_type', 'story_hn_item_id', 'rank', 'snapshot_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['current', 'archived']
  - constraint: rank >= 1
  - constraint: unique(feed_type, snapshot_at, rank)
  - constraint: unique(feed_type, snapshot_at, story_hn_item_id)
  - constraint: only allow story_hn_item_id that exists in hn_items with item_type='story'
- `search_queries.json` — Executed search requests and their parameters, to support caching, analytics, and deterministic pagination for search_stories. (18 rows; fields: ['id', 'query_text', 'search_by_date', 'requested_num_results', 'normalized_query_hash', 'status', 'executed_at', 'expires_at', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'completed', 'failed', 'expired']
  - constraint: requested_num_results between 1 and 100
  - constraint: length(trim(query_text)) >= 1
  - constraint: unique(normalized_query_hash) where status in ('queued','running','completed')
- `search_results.json` — Result rows for a given search query, mapping to stories (HN items) with ranking and lightweight snippets. (18 rows; fields: ['id', 'search_query_id', 'story_hn_item_id', 'rank', 'match_score', 'snippet', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active']
  - constraint: rank >= 1
  - constraint: unique(search_query_id, rank)
  - constraint: unique(search_query_id, story_hn_item_id)
  - constraint: only allow story_hn_item_id that exists in hn_items with item_type='story'

## Business rules enforced by the tools

- get_stories(story_type, num_stories) reads from hn_story_feeds where feed_type=story_type and status='current', ordered by rank asc, limited by num_stories (default and maximum enforced server-side).
- If hn_story_feeds has no current snapshot for a feed_type or the snapshot is stale, the service must fetch upstream, upsert hn_items for the returned story ids (item_type='story'), and write a new feed snapshot (archiving the previous current snapshot).
- get_story_info(story_id) resolves hn_items by hn_item_id=story_id and item_type='story'; it then returns the story plus all hn_items where root_story_hn_item_id=story_id and item_type='comment' (or fetched/upserted if missing/stale), reconstructing the tree using parent_hn_item_id.
- get_user_info(user_name, num_stories) resolves hn_users.username=user_name (fetch/upsert if missing/stale) and returns the user profile plus their submitted stories from hn_items where by_user_id matches and item_type='story', ordered by time_posted_at desc, limited by num_stories.
- search_stories(query, search_by_date, num_results) must create or reuse a search_queries row keyed by normalized_query_hash; if cached results exist and not expired, return associated search_results ordered by rank asc limited by num_results.
- When executing a new search, the service must set search_queries.status from queued->running->completed/failed, persist results into search_results, and upsert any referenced stories into hn_items (item_type='story').
- num_stories and num_results must be clamped to [1, 100] regardless of client input; missing values default to 10 where documented.
- Foreign key integrity must be enforced: hn_items.by_user_id references hn_users.id when present; search_results.search_query_id must exist; hn_story_feeds.story_hn_item_id and search_results.story_hn_item_id must correspond to hn_items.hn_item_id for a story.
- Deleting or marking an hn_items row as deleted/dead must not cascade-delete related feed memberships or search results; reads must filter out non-active items unless explicitly requested by internal maintenance jobs.