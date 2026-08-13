# X V2 MCP Server — local MCP environment

This backend models a minimal but production-plausible X/Twitter-like service facade used by an MCP server: users, tweets (including replies and quotes), social graph (follows), likes, and user-curated lists. It supports read workflows (fetch tweets, mentions, trending, search, lists) and write workflows (post/reply/quote, like, follow/unfollow, list membership changes) with basic lifecycle status, integrity constraints, and auditability.

Repository: https://github.com/NexusX-MCP/x-v2-server
Homepage: https://smithery.ai/server/@NexusX-MCP/x-v2-server

## Datastore

- `users.json` — Represents X users (accounts). Used for lookups by username, tweet authorship, follow graph endpoints, mentions resolution, and list ownership/membership. (17 rows; fields: ['id', 'x_user_id', 'username', 'normalized_username', 'display_name', 'bio', 'profile_image_url', 'is_verified', 'is_protected', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(normalized_username)
  - constraint: unique(x_user_id) where x_user_id is not null
  - constraint: username length between 1 and 15 (X-like), characters limited to [A-Za-z0-9_]
  - constraint: status != 'deleted' required for auth/interactive actions (post/like/follow/list modifications)
- `tweets.json` — Stores tweets authored by users, including replies and quote tweets. Supports fetching by id, fetching by user id, mentions queries, and full-text search. (18 rows; fields: ['id', 'x_tweet_id', 'author_user_id', 'text', 'lang', 'reply_to_tweet_id', 'quote_of_tweet_id', 'conversation_root_tweet_id', 'source', 'public_metrics', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['published', 'hidden', 'deleted']
  - constraint: author_user_id references users.id on delete restrict
  - constraint: reply_to_tweet_id references tweets.id on delete restrict
  - constraint: quote_of_tweet_id references tweets.id on delete restrict
  - constraint: not (reply_to_tweet_id is not null and quote_of_tweet_id is not null) (a tweet cannot be both reply and quote)
- `tweet_entities.json` — Child table for tweet entities: mentions (used by get_user_mentions), hashtags (used by trending), and URLs. Enables efficient indexing without parsing tweet text on every request. (18 rows; fields: ['id', 'tweet_id', 'entity_type', 'start_index', 'end_index', 'mentioned_user_id', 'tag', 'normalized_tag', 'url', 'created_at', 'updated_at'])
  - lifecycle `entity_type`: ['mention', 'hashtag', 'url']
  - constraint: tweet_id references tweets.id on delete cascade
  - constraint: if entity_type='mention' then mentioned_user_id is not null and tag is null and url is null
  - constraint: if entity_type='hashtag' then normalized_tag is not null and mentioned_user_id is null and url is null
  - constraint: if entity_type='url' then url is not null and mentioned_user_id is null and tag is null
- `social_edges.json` — Stores relationship edges: follows and likes. Covers follow_user, unfollow_user, and like_tweet. Also used to compute social context for reads. (18 rows; fields: ['id', 'edge_type', 'actor_user_id', 'target_user_id', 'target_tweet_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: actor_user_id references users.id on delete cascade
  - constraint: if edge_type='follow' then target_user_id is not null and target_tweet_id is null
  - constraint: if edge_type='like' then target_tweet_id is not null and target_user_id is null
  - constraint: actor_user_id != target_user_id for follow edges
- `lists.json` — User-curated lists and their memberships. Supports create_list, add_list_member, remove_list_member, and get_owned_lists. (18 rows; fields: ['id', 'owner_user_id', 'name', 'description', 'visibility', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: owner_user_id references users.id on delete cascade
  - constraint: unique(owner_user_id, name) where status != 'deleted'
  - constraint: name length between 1 and 100
  - constraint: maximum lists per owner enforced by business rule/quota (e.g., <= 1000)
- `list_members.json` — Join table for list membership. Tracks add/remove events and current membership status. (18 rows; fields: ['id', 'list_id', 'member_user_id', 'added_by_user_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: list_id references lists.id on delete cascade
  - constraint: member_user_id references users.id on delete cascade
  - constraint: added_by_user_id references users.id on delete restrict
  - constraint: unique(list_id, member_user_id)

## Business rules enforced by the tools

- Tool get_user_by_username performs a case-insensitive lookup on users.normalized_username and returns only users.status='active' unless an admin mode is explicitly enabled.
- Tool get_tweets_by_userid selects tweets where tweets.author_user_id = :user_id and tweets.status='published', ordered by created_at desc, with pagination handled at the API layer (not present in tool parameters).
- Tool get_tweet_by_id fetches a single tweet by tweets.id or tweets.x_tweet_id (if the MCP server accepts either internally); it must not return tweets.status='deleted'.
- Tool get_user_mentions returns tweets that mention a given user by joining tweet_entities where entity_type='mention' and mentioned_user_id=:user_id, and only includes tweets.status='published'.
- Tool post_tweet creates a tweets row with status='published', increments any relevant derived metrics asynchronously, and inserts tweet_entities for detected mentions/hashtags/urls.
- Tool reply_to_tweet creates a tweets row with reply_to_tweet_id set; it must validate the parent tweet exists and is not deleted/hidden, and set conversation_root_tweet_id to the root of the parent thread (or parent itself if no root).
- Tool quote_tweet creates a tweets row with quote_of_tweet_id set; it must validate the quoted tweet exists and is not deleted/hidden and then increments quoted tweet public_metrics.quote_count (transactionally or via job).
- Tool like_tweet upserts a social_edges row with edge_type='like' and (actor_user_id, target_tweet_id); setting status to 'active' must increment tweets.public_metrics.like_count exactly once, and re-liking an already active like is idempotent.
- Tool follow_user upserts a social_edges row with edge_type='follow' and (actor_user_id, target_user_id); setting status to 'active' must be idempotent, and actor_user_id must not equal target_user_id.
- Tool unfollow_user sets the corresponding follow edge status='revoked' (idempotent); it must not delete the row to preserve audit history.
- Tool search_tweets queries tweets where status='published' and matches either a text search index on tweets.text and/or hashtag entities via tweet_entities.normalized_tag; results are ordered by recency unless a relevance score is available.
- Tool get_trending_topics aggregates tweet_entities where entity_type='hashtag' over a recent time window (e.g., last 24h) joining tweets for created_at and status='published', and returns the top N normalized_tag by count with optional smoothing.
- Tool create_list inserts into lists with status='active' and visibility defaulted if not provided by the caller; list names are unique per owner among non-deleted lists.
- Tool add_list_member upserts into list_members (unique(list_id, member_user_id)) setting status='active'; only the list owner may add members.
- Tool remove_list_member sets list_members.status='removed' (idempotent); only the list owner may remove members.
- Tool get_owned_lists returns lists where owner_user_id=:user_id and status in ('active','archived'), ordered by created_at desc.