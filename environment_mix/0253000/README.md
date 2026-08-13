# X (Twitter) Management — local MCP environment

This backend supports an X (Twitter) management service that can search for tweets, fetch tweet details, generate reply suggestions, and post tweets or replies (optionally with media). It stores connected X accounts, ingested/search-retrieved tweets, outbound posts, and AI-generated reply drafts, with auditability and rate/quota enforcement per account.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@xonack/apex-mcp

## Datastore

- `x_accounts.json` — Connected X/Twitter accounts and their auth state, used to execute searches and posting actions on behalf of a user/tenant. (18 rows; fields: ['id', 'handle', 'x_user_id', 'display_name', 'auth_status', 'access_token_ciphertext', 'refresh_token_ciphertext', 'token_expires_at', 'default_language', 'posting_enabled', 'daily_post_limit', 'daily_search_limit', 'daily_ai_reply_limit', 'created_at', 'updated_at'])
  - lifecycle `auth_status`: ['connected', 'revoked', 'expired', 'error']
  - constraint: unique(handle)
  - constraint: unique(x_user_id)
  - constraint: daily_post_limit >= 0
  - constraint: daily_search_limit >= 0
- `tweets.json` — Tweets known to the system, sourced from search results, explicit fetches, or created as outbound posts/replies. (18 rows; fields: ['id', 'x_tweet_id', 'author_x_user_id', 'author_handle', 'text', 'lang', 'conversation_x_tweet_id', 'in_reply_to_x_tweet_id', 'quoted_x_tweet_id', 'retweeted_x_tweet_id', 'like_count', 'reply_count', 'retweet_count', 'quote_count', 'source_type', 'observed_at', 'posted_by_account_id', 'x_created_at', 'created_at', 'updated_at'])
  - lifecycle `source_type`: ['searched', 'fetched', 'posted']
  - constraint: unique(x_tweet_id) where x_tweet_id IS NOT NULL
  - constraint: like_count >= 0 where like_count IS NOT NULL
  - constraint: reply_count >= 0 where reply_count IS NOT NULL
  - constraint: retweet_count >= 0 where retweet_count IS NOT NULL
- `search_queries.json` — Search operations executed against X, used to power search_tweets and to cache/record results for later inspection. (18 rows; fields: ['id', 'account_id', 'query_text', 'status', 'requested_limit', 'cursor', 'provider_request_id', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: requested_limit between 1 and 100
  - constraint: account_id must reference existing x_accounts.id
  - constraint: error_code IS NOT NULL iff status = 'failed'
  - constraint: started_at IS NOT NULL iff status in ('running','succeeded','failed','cancelled')
- `search_results.json` — Join table mapping a search query to the tweets returned, preserving rank/order and allowing dedup across searches. (18 rows; fields: ['id', 'search_query_id', 'tweet_id', 'rank', 'matched_at', 'created_at', 'updated_at'])
  - lifecycle `rank`: []
  - constraint: unique(search_query_id, tweet_id)
  - constraint: unique(search_query_id, rank)
  - constraint: rank >= 1
  - constraint: FK(search_query_id) references search_queries.id on delete cascade
- `outbound_posts.json` — Outbound tweet/reply publishing requests and their delivery status to X; powers post_tweet and post_reply_to_tweet. (18 rows; fields: ['id', 'account_id', 'post_type', 'in_reply_to_tweet_id', 'body_text', 'media', 'status', 'provider_tweet_id', 'published_tweet_id', 'error_code', 'error_message', 'sent_at', 'published_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'queued', 'sending', 'published', 'failed', 'cancelled']
  - constraint: FK(account_id) references x_accounts.id
  - constraint: in_reply_to_tweet_id IS NOT NULL iff post_type='reply'
  - constraint: char_length(body_text) between 1 and 280 (enforced at publish time; storage allows larger but service rejects >280)
  - constraint: provider_tweet_id IS NOT NULL iff status='published'
- `reply_generations.json` — AI-assisted reply suggestion requests and outputs; powers generate_reply and generate_reply_to_tweet. (18 rows; fields: ['id', 'account_id', 'mode', 'target_tweet_id', 'input_message', 'status', 'model', 'temperature', 'reply_text', 'safety_flags', 'token_input', 'token_output', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: FK(account_id) references x_accounts.id
  - constraint: target_tweet_id IS NOT NULL iff mode='to_tweet'
  - constraint: input_message IS NOT NULL iff mode='to_message'
  - constraint: temperature between 0 and 2 where temperature IS NOT NULL

## Business rules enforced by the tools

- search_tweets creates a search_queries row (status queued->running->succeeded/failed) and upserts tweets for each returned provider tweet id, then inserts search_results with contiguous rank starting at 1.
- get_tweet resolves a tweet by provider id if supplied by the integration; if not present locally, it fetches from X, inserts/updates tweets with source_type='fetched', and returns the tweet payload.
- post_tweet creates an outbound_posts row with post_type='tweet' and status='queued'; publishing transitions to 'sending' then 'published' or 'failed'. On 'published', a tweets row is created/updated with source_type='posted' and linked via outbound_posts.published_tweet_id and provider_tweet_id.
- post_reply_to_tweet requires an existing target tweet record (tweets.id) or a fetch step that creates it; it creates outbound_posts with post_type='reply' and in_reply_to_tweet_id set, validates body_text length <= 280, and if media is present validates it is an image payload accepted by the provider adapter.
- generate_reply_to_tweet creates reply_generations with mode='to_tweet' and target_tweet_id set; the system may fetch/store the tweet first if not present. The resulting reply_text must be <= 280 characters.
- generate_reply creates reply_generations with mode='to_message' and input_message set; reply_text returned must be <= 280 characters.
- Per x_accounts quotas: in a rolling 24h window (or per calendar day, implementation-defined), successful outbound_posts where status='published' must not exceed daily_post_limit; search_queries executions must not exceed daily_search_limit; reply_generations with status='succeeded' must not exceed daily_ai_reply_limit.
- If x_accounts.auth_status is not 'connected' or posting_enabled=false, attempts to publish (post_tweet/post_reply_to_tweet) must be rejected before creating a 'sending' outbound_posts state (may still create a 'failed' record for audit).
- FK integrity is enforced: deleting an x_accounts row is disallowed if referenced by outbound_posts or reply_generations; deleting a search_queries row cascades to search_results but not to tweets.
- Status transitions must follow the declared lifecycle maps; invalid transitions are rejected atomically.