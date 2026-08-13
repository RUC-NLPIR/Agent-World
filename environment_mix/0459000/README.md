# X MCP — local MCP environment

This backend powers an MCP service that reads Twitter/X data (profiles and timelines) and produces AI-generated artifacts: profile analyses, timeline summaries, suggested tweets, and comparative perspective reports. It stores ingested X entities (accounts, tweets), caches fetch jobs, and persists user-facing generation runs with outputs and lifecycle/status for auditing and rate limiting.

Repository: https://github.com/aaronjmars
Homepage: https://smithery.ai/server/@aaronjmars/x-mcp

## Datastore

- `workspaces.json` — Tenant/workspace container for API usage, quotas, and grouping of analyses/generations. Even if the tool surface has no explicit auth parameters, production systems typically bind requests to a workspace via API key. (12 rows; fields: ['id', 'name', 'status', 'default_x_handle', 'plan', 'monthly_run_quota', 'monthly_token_quota', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: monthly_run_quota >= 0
  - constraint: monthly_token_quota >= 0
  - constraint: default_x_handle matches ^@?[A-Za-z0-9_]{1,15}$ when not null
- `api_keys.json` — API keys used to authenticate MCP calls and attribute usage to a workspace. (12 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(workspace_id, name)
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
- `x_accounts.json` — Cached Twitter/X account profiles used for analysis and timeline retrieval. (33 rows; fields: ['id', 'platform', 'x_user_id', 'handle', 'display_name', 'bio', 'location', 'website_url', 'followers_count', 'following_count', 'tweet_count', 'verified_type', 'profile_image_url', 'status', 'last_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'not_found', 'blocked', 'suspended']
  - constraint: unique(platform, handle)
  - constraint: unique(platform, x_user_id) where x_user_id is not null
  - constraint: followers_count >= 0 when not null
  - constraint: following_count >= 0 when not null
- `x_tweets.json` — Cached tweets used to build timelines and feed summarization/analysis and tweet-style generation. (32 rows; fields: ['id', 'author_account_id', 'x_tweet_id', 'text', 'lang', 'conversation_id', 'in_reply_to_x_tweet_id', 'is_retweet', 'is_quote', 'like_count', 'reply_count', 'retweet_count', 'quote_count', 'posted_at', 'ingested_at', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `availability_status`: ['available', 'unavailable', 'deleted']
  - constraint: unique(author_account_id, x_tweet_id)
  - constraint: fk(author_account_id) references x_accounts(id) on delete cascade
  - constraint: like_count >= 0 when not null
  - constraint: reply_count >= 0 when not null
- `generation_runs.json` — Durable record of each tool invocation (analyze profile, summarize timeline, generate tweet, compare perspectives), including inputs resolved by config, fetched entity snapshots, and generated outputs. (37 rows; fields: ['id', 'workspace_id', 'api_key_id', 'tool_name', 'status', 'target_account_id', 'comparison_account_id', 'input_params', 'resolved_context', 'source_tweet_ids', 'output_text', 'output_json', 'model', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'cost_usd', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: fk(api_key_id) references api_keys(id) on delete set null
  - constraint: fk(target_account_id) references x_accounts(id) on delete set null
  - constraint: fk(comparison_account_id) references x_accounts(id) on delete set null

## Business rules enforced by the tools

- Every tool call creates exactly one generation_runs row with tool_name set to the invoked tool and input_params stored verbatim ({} for the current surface).
- Requests are authenticated by an API key; the resolved workspace_id is taken from api_keys.workspace_id. If auth is disabled (dev mode), runs must still be attributed to a default workspace.
- For analyze_twitter_profile: generation_runs.target_account_id must be set (resolved from workspaces.default_x_handle or server config). The service must fetch/update x_accounts for that handle if last_fetched_at is older than a configured TTL (e.g., 15 minutes) or missing.
- For summarize_twitter_timeline: generation_runs.target_account_id must be set; the service must select a bounded set of tweets (e.g., most recent N) from x_tweets where author_account_id=target_account_id and deleted_at is null; the chosen internal tweet ids must be written to generation_runs.source_tweet_ids.
- For generate_tweet: generation_runs.target_account_id should be set to the style source account; the output_text must be a single tweet draft. If the system uses timeline grounding, it must record the grounding tweet ids in source_tweet_ids; otherwise source_tweet_ids must be an empty array.
- For compare_perspectives: both generation_runs.target_account_id and generation_runs.comparison_account_id must be non-null and different. The run must store source_tweet_ids that may include tweets from one or both accounts used as evidence.
- Quota enforcement: before moving a run from queued to running, the service must ensure the workspace is active and has not exceeded monthly_run_quota. Before finalizing succeeded, the service must ensure monthly_token_quota is not exceeded by adding total_tokens for the month; if exceeded, the run must be marked failed with error_code='quota_exceeded'.
- Status transitions must follow the declared lifecycle; direct updates that skip intermediate states (e.g., queued -> succeeded) are rejected.
- FK integrity: x_tweets.author_account_id must reference an existing x_accounts row; deletion of an account must cascade delete its cached tweets, but not delete generation_runs (runs retain nullable references).
- Uniqueness: x_accounts must be unique by (platform, handle) and x_tweets unique by (author_account_id, x_tweet_id) to prevent duplicate ingestion during repeated fetches.