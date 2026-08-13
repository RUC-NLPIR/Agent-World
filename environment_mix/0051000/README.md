# X Twitter Server — local MCP environment

This backend stores local representations of X/Twitter users and tweets plus the authenticated account context used by the MCP server to act on behalf of a user. It records social graph edges (follow/subscription), tweet interactions (favorites/likes, bookmarks, poll votes), and also persists read-side artifacts like timelines, searches, trends, and highlights for caching/auditing and rate-limit protection.

Repository: https://github.com/rafaljanicki/x-twitter-mcp-server
Homepage: https://smithery.ai/server/@rafaljanicki/x-twitter-mcp-server

## Datastore

- `accounts.json` — Authenticated X/Twitter accounts and server-side API access context (tokens/session), used as the actor for all tools and as the owner of private user-specific resources like bookmarks, likes, timelines. (12 rows; fields: ['id', 'x_user_id', 'screen_name', 'display_name', 'auth_type', 'access_token', 'refresh_token', 'token_expires_at', 'cookie_jar', 'status', 'last_used_at', 'rate_limit_state', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'expired', 'disabled']
  - constraint: unique(x_user_id, auth_type) where status in ('active','expired')
  - constraint: screen_name != ''
  - constraint: token_expires_at is null OR token_expires_at > created_at
- `users.json` — X/Twitter user profiles cached by the server for lookups, relationship listing, mentions, highlights, and attribution on tweets. (31 rows; fields: ['id', 'x_id', 'screen_name', 'display_name', 'bio', 'location', 'profile_image_url', 'verified_type', 'protected', 'followers_count', 'following_count', 'statuses_count', 'favourites_count', 'joined_at', 'last_fetched_at', 'created_at', 'updated_at'])
  - constraint: unique(x_id)
  - constraint: unique(lower(screen_name))
  - constraint: followers_count is null OR followers_count >= 0
  - constraint: following_count is null OR following_count >= 0
- `tweets.json` — Tweets/statuses posted or observed by the server, including replies, media metadata, poll metadata, and deletion state. Supports posting, deleting, details, timelines, highlights, mentions, and search result caching. (36 rows; fields: ['id', 'x_id', 'author_user_x_id', 'created_on_x_at', 'text', 'lang', 'conversation_x_id', 'in_reply_to_tweet_x_id', 'in_reply_to_user_x_id', 'quote_tweet_x_id', 'hashtags', 'mentions_user_x_ids', 'media', 'poll', 'public_metrics', 'status', 'deleted_on_x_at', 'source', 'created_at', 'updated_at'])
  - lifecycle `status`: ['visible', 'deleted', 'withheld', 'tombstoned']
  - constraint: unique(x_id)
  - constraint: text is null OR length(text) <= 10000
  - constraint: in_reply_to_tweet_x_id is null OR in_reply_to_tweet_x_id != x_id
  - constraint: deleted_on_x_at is null OR status = 'deleted'
- `user_relationships.json` — Edges between users, covering followers/following and subscription relationships. Used to serve followers/following/common followers/subscriptions tools and to cache social graph responses. (31 rows; fields: ['id', 'from_user_x_id', 'to_user_x_id', 'relationship_type', 'status', 'observed_at', 'source', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: unique(from_user_x_id, to_user_x_id, relationship_type)
  - constraint: from_user_x_id != to_user_x_id
- `tweet_engagements.json` — Per-account interactions with tweets: favorites/likes, bookmarks, and poll votes. Drives favorite/unfavorite, bookmark/delete, delete all bookmarks, and vote on poll behavior. (33 rows; fields: ['id', 'account_id', 'tweet_x_id', 'engagement_type', 'status', 'poll_choice_index', 'x_engagement_id', 'engaged_at', 'removed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: unique(account_id, tweet_x_id, engagement_type)
  - constraint: poll_choice_index is null OR poll_choice_index >= 0
  - constraint: engagement_type != 'poll_vote' OR poll_choice_index is not null
  - constraint: removed_at is null OR status = 'removed'
- `feeds_and_searches.json` — Materialized/cached read queries and their results for timelines, search, trends, highlights, and mentions. Each row stores the request context and a denormalized list of resulting tweet ids/topics to serve read tools quickly and for auditing/rate-limit backoff. (38 rows; fields: ['id', 'account_id', 'kind', 'subject_user_x_id', 'query', 'cursor', 'result_tweet_x_ids', 'result_topics', 'response_meta', 'status', 'fetched_at', 'expires_at', 'error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'failed']
  - constraint: kind != 'search' OR query is not null
  - constraint: kind in ('highlights','mentions') implies subject_user_x_id is not null
  - constraint: kind = 'trends' implies result_topics is not null
  - constraint: kind != 'trends' implies result_tweet_x_ids is not null

## Business rules enforced by the tools

- All mutating tools (post_tweet, delete_tweet, create_poll_tweet, vote_on_poll, favorite_tweet, unfavorite_tweet, bookmark_tweet, delete_bookmark, delete_all_bookmarks) MUST be associated with exactly one active accounts row; if no active account exists, the tool must fail with an authentication error.
- get_user_profile MUST return the users row referenced by the active account (accounts.x_user_id -> users.x_id); if missing, the service must fetch from X and upsert users before returning.
- get_user_by_id and get_user_by_screen_name MUST upsert into users and enforce uniqueness on users.x_id and lower(users.screen_name).
- get_user_followers and get_user_following MUST upsert users for any returned profiles and upsert user_relationships edges with relationship_type='follows' and status='active'; edges not observed in the latest fetch MAY be marked inactive only if the fetch is known-complete (response_meta.partial=false).
- get_user_followers_you_know MUST compute the intersection of follower sets using user_relationships where relationship_type='follows' and status='active', scoped to the relevant subject users; if the cache is missing, it must fetch followers lists from X then populate user_relationships.
- get_user_subscriptions MUST upsert user_relationships with relationship_type='subscribes' and status='active' for the subject user.
- post_tweet MUST create (or update) a tweets row with source='posted_via_api' and status='visible' after X confirms success; if X returns an id already present, the implementation must be idempotent (update existing row).
- delete_tweet MUST transition tweets.status from 'visible' to 'deleted' and set deleted_on_x_at when X confirms deletion; deleting an already-deleted tweet MUST be idempotent.
- create_poll_tweet MUST store poll metadata in tweets.poll; it MUST validate poll option count between 2 and 4 and duration between 300 and 604800 seconds before calling X (if provided by the upstream tool implementation).
- vote_on_poll MUST only create/update tweet_engagements with engagement_type='poll_vote' when the target tweet has a non-null tweets.poll; poll_choice_index must be within the poll options array bounds.
- favorite_tweet and unfavorite_tweet MUST upsert tweet_engagements for the (account_id, tweet_x_id) pair with engagement_type='favorite', toggling status between active/removed; operations MUST be idempotent.
- bookmark_tweet, delete_bookmark MUST upsert/toggle tweet_engagements similarly for engagement_type='bookmark'; delete_all_bookmarks MUST set status='removed' and removed_at for all active bookmark engagements for the account in a single transaction.
- get_tweet_details MUST upsert tweets (and referenced users) and must not overwrite tweets.status='deleted' back to 'visible' unless X explicitly indicates the tweet exists again (rare/should generally be prevented).
- get_timeline and get_latest_timeline MUST create a feeds_and_searches row with kind home_timeline_for_you/home_timeline_following and store ordered result_tweet_x_ids; fetched tweets/users must be upserted.
- search_twitter MUST create a feeds_and_searches row with kind='search' and query set; the service SHOULD apply a cache TTL (expires_at) and reuse a fresh cached entry for identical (account_id, query, cursor) requests within TTL.
- get_trends MUST create a feeds_and_searches row with kind='trends' and result_topics populated; it SHOULD apply a short TTL (e.g., 2-10 minutes) via expires_at.
- get_highlights_tweets MUST create a feeds_and_searches row with kind='highlights' and subject_user_x_id; it MUST upsert tweets/users returned.
- get_user_mentions MUST create a feeds_and_searches row with kind='mentions' and subject_user_x_id; it MUST upsert tweets/users returned.