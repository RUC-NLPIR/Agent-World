# Hacker News Integration — local MCP environment

This backend powers a Hacker News integration by caching Hacker News items (stories/comments/jobs/polls), users, and the relationships between items (story-to-comment, comment-to-reply). It also records search requests and list-fetch requests (top/new/best/ask/show/job) to support pagination, rate limiting, and efficient repeated queries while keeping cached content fresh.

Repository: https://github.com/devabdultech/hn-mcp
Homepage: https://smithery.ai/server/@devabdultech/hn-mcp

## Datastore

- `hn_items.json` — Cached Hacker News items from the official HN Firebase API (stories, comments, jobs, polls, etc.). Serves getStory/getComment and underpins story-with-comments and comment tree. (19 rows; fields: ['id', 'hn_item_id', 'item_type', 'status', 'title', 'text', 'url', 'score', 'descendants', 'author_user_id', 'hn_author', 'parent_hn_item_id', 'root_story_hn_item_id', 'kids_hn_item_ids', 'hn_created_at', 'fetched_at', 'etag', 'raw', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'dead', 'tombstoned']
  - constraint: unique(hn_item_id)
  - constraint: hn_item_id > 0
  - constraint: item_type in ('story','comment','job','poll','pollopt')
  - constraint: score is null or score >= 0
- `hn_item_edges.json` — Normalized parent->child relationships between HN items (used for getComments and getCommentTree; also enables ordering). (18 rows; fields: ['id', 'parent_item_id', 'child_item_id', 'root_story_item_id', 'depth', 'sort_order', 'created_at', 'updated_at'])
  - constraint: unique(parent_item_id, child_item_id)
  - constraint: parent_item_id != child_item_id
  - constraint: depth is null or depth >= 0
  - constraint: sort_order is null or sort_order >= 0
- `hn_users.json` — Cached Hacker News user profiles. Serves getUser and supports author lookups for items. (18 rows; fields: ['id', 'hn_username', 'status', 'about', 'karma', 'hn_created_at', 'submitted_hn_item_ids', 'fetched_at', 'raw', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'tombstoned']
  - constraint: unique(hn_username)
  - constraint: length(hn_username) >= 1
  - constraint: karma is null or karma >= 0
  - constraint: fetched_at <= now()
- `hn_story_lists.json` — Materialized/cached story id lists for getStories by type (top/new/best/ask/show/job), including fetch metadata. (18 rows; fields: ['id', 'list_type', 'status', 'hn_story_ids', 'fetched_at', 'expires_at', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'refreshing', 'failed']
  - constraint: unique(list_type)
  - constraint: json_array_length(hn_story_ids) >= 0
  - constraint: fetched_at <= now()
  - constraint: expires_at is null or expires_at >= fetched_at
- `hn_requests.json` — Request/usage log for tool calls (search, getStory, getStoryWithComments, getStories, getComment, getComments, getCommentTree, getUser, getUserSubmissions). Enables pagination tracking, cache hit analysis, and quota enforcement. (19 rows; fields: ['id', 'tool_name', 'status', 'query', 'search_type', 'page', 'hits_per_page', 'story_hn_item_id', 'comment_hn_item_id', 'stories_type', 'limit', 'user_hn_username', 'response_cached_object_ids', 'upstream_provider', 'upstream_latency_ms', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'served_from_cache', 'fetched_upstream', 'failed']
  - constraint: page is null or page >= 0
  - constraint: hits_per_page is null or (hits_per_page >= 1 and hits_per_page <= 100)
  - constraint: limit is null or (limit >= 1 and limit <= 500)
  - constraint: story_hn_item_id is null or story_hn_item_id > 0

## Business rules enforced by the tools

- Search requests must persist the tuple (query, search_type, page, hits_per_page) in hn_requests; page defaults to 0 and hits_per_page defaults to 20 when omitted.
- getStories(type, limit) must read from hn_story_lists for the given list_type; if the list is stale/expired it may transition status stale->refreshing and then to fresh|failed after refetch.
- getStory(id) must return an hn_items row where hn_item_id=id and item_type='story'; if absent or stale, the service fetches upstream and upserts hn_items with fetched_at updated.
- getComment(id) must return an hn_items row where hn_item_id=id and item_type='comment'; if absent or stale, fetch upstream and upsert.
- getComments(storyId, limit) must return the first N comment items under the given story ordered by hn_item_edges.sort_order (fallback: hn_created_at); limit defaults to 30 and is capped at 500.
- getCommentTree(storyId) must traverse hn_item_edges starting at root_story_item_id matching the story and return a hierarchical structure; cycles are prevented by the unique(parent_item_id, child_item_id) constraint and parent_item_id != child_item_id.
- getStoryWithComments(id) must return the story plus comments; it may combine hn_items and hn_item_edges to assemble replies and must not include items whose hn_items.status in ('deleted','dead','tombstoned') unless explicitly configured (default exclusion).
- getUser(id) must return hn_users.hn_username=id; if absent or stale, fetch upstream and upsert hn_users with fetched_at updated.
- getUserSubmissions(id) must use hn_users.submitted_hn_item_ids when present; for each referenced item id, the service may lazily hydrate hn_items rows on demand (upsert by hn_item_id).
- When an upstream payload marks an item as deleted or dead, hn_items.status must transition active->deleted|dead and must not transition back to active in later updates.
- FK integrity must be enforced for hn_item_edges: parent_item_id, child_item_id, and root_story_item_id must reference existing hn_items.id rows; edge creation requires the referenced items to exist (create items first, then edges).
- All request logging rows in hn_requests must be immutable in meaning: tool_name and parameter columns set at creation time; only status, latency, error_message, and updated_at may change after creation.