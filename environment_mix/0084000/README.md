# Bluesky MCP Server — local MCP environment

This backend powers an MCP server that proxies Bluesky (AT Protocol) operations for an authenticated user, while caching key entities (actors, posts, feeds/lists) and recording user actions (likes, follows, created posts). It also tracks per-tool invocations for audit, rate limiting, and to support read tools like timelines, searches, and trend lookups from cached results when available.

Repository: https://github.com/brianellin/bsky-mcp-server
Homepage: https://smithery.ai/server/@brianellin/bsky-mcp-server

## Datastore

- `mcp_api_keys.json` — API keys/tokens used to authenticate clients of this MCP server, including quota and lifecycle state. (12 rows; fields: ['id', 'key_hash', 'label', 'status', 'quota_requests_per_minute', 'quota_requests_per_day', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: quota_requests_per_minute between 1 and 6000
  - constraint: quota_requests_per_day between 1 and 1000000
  - constraint: status in ('active','suspended','revoked')
- `bsky_sessions.json` — Authenticated Bluesky (AT Protocol) sessions associated with an MCP API key, including token state and the active actor DID. (12 rows; fields: ['id', 'api_key_id', 'actor_did', 'actor_handle', 'pds_url', 'access_jwt_enc', 'refresh_jwt_enc', 'expires_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'revoked']
  - constraint: fk(api_key_id) references mcp_api_keys(id) on delete cascade
  - constraint: unique(api_key_id, actor_did, pds_url) where status != 'revoked'
  - constraint: expires_at >= created_at
- `actors.json` — Cached Bluesky actors (users) referenced by profiles, follows, likes, timelines, and search results. (19 rows; fields: ['id', 'did', 'handle', 'display_name', 'description_text', 'avatar_url', 'banner_url', 'follows_count', 'followers_count', 'posts_count', 'indexed_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'tombstoned']
  - constraint: unique(did)
  - constraint: unique(handle) where handle is not null
  - constraint: follows_count is null or follows_count >= 0
  - constraint: followers_count is null or followers_count >= 0
- `posts.json` — Cached Bluesky posts plus server-recorded interactions (likes) and provenance (timeline/feed/search fetches). (19 rows; fields: ['id', 'uri', 'cid', 'author_actor_id', 'text', 'lang', 'reply_parent_uri', 'reply_root_uri', 'like_count', 'repost_count', 'reply_count', 'quote_count', 'indexed_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['visible', 'deleted', 'tombstoned']
  - constraint: unique(uri)
  - constraint: fk(author_actor_id) references actors(id)
  - constraint: like_count is null or like_count >= 0
  - constraint: repost_count is null or repost_count >= 0
- `social_graph_and_collections.json` — Join/child entities for follows, likes, feeds, lists, pinned items, and cached trend/search results required to serve timeline/feed/list tools. (19 rows; fields: ['id', 'row_type', 'session_id', 'actor_id', 'post_id', 'subject_actor_id', 'feed_uri', 'list_uri', 'name', 'description_text', 'position', 'rank', 'cursor', 'tool_name', 'request_params', 'response_meta', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'deleted']
  - constraint: fk(session_id) references bsky_sessions(id) on delete cascade
  - constraint: fk(actor_id) references actors(id)
  - constraint: fk(subject_actor_id) references actors(id)
  - constraint: fk(post_id) references posts(id)

## Business rules enforced by the tools

- Every tool invocation must be recorded as a social_graph_and_collections row with row_type='tool_invocation', tool_name set, session_id set when the tool requires authentication, and request_params captured (may be empty object given current tool schemas).
- Requests must be rejected when the associated mcp_api_keys.status != 'active'.
- Rate limiting: for each api_key_id, tool invocations in the last 60 seconds must not exceed quota_requests_per_minute; invocations since UTC day start must not exceed quota_requests_per_day.
- bsky_sessions.status must be 'active' to perform authenticated tools: create-post, get-liked-posts, like-post, follow-user, get-pinned-feeds. If expires_at < now(), session transitions to 'expired' before performing the tool.
- create-post must insert a posts row (uri assigned from upstream), ensure author_actor_id matches the session actor_did (creating/upserting the actors row if missing), and set posts.status='visible'.
- like-post must upsert a social_graph_and_collections row_type='post_like' for (session_id, post_id) with status='active'; liking the same post twice is idempotent (no duplicate active rows).
- follow-user must upsert a social_graph_and_collections row_type='follow_edge' with actor_id = follower (session actor) and subject_actor_id = followed actor, status='active'; following the same user twice is idempotent.
- get-post-likes must return actors who liked the post by reading social_graph_and_collections rows row_type='post_like' joined to actors; if upstream is queried, results must be cached by creating/updating those rows.
- get-follows must return follow edges where row_type='follow_edge' and actor_id matches the requested person (session actor if unactioned by params); cache results from upstream in follow_edge rows and mark older rows 'stale' when refreshing.
- get-timeline-posts/get-feed-posts/get-list-posts/get-user-posts must cache returned posts (upsert posts + actors) and may record membership as feed_item/list_item rows keyed by feed_uri/list_uri plus post_id; older membership rows can be marked 'stale' when refreshing.
- search-posts/search-people/search-feeds must create a search_query row capturing request_params and then store hits as search_hit_post rows (post search) or actor_id-bearing rows (people search) and feed_def rows (feed search) as applicable; repeated identical searches may reuse cached results when not stale.
- get-trends must upsert trend_topic rows with name and rank; trend topics older than a configured TTL (e.g., 30 minutes) must be marked 'stale' and refreshed from upstream.
- list-resources is served from static server metadata but still logs a tool_invocation row; it does not require a session_id.