# Reddit Content Fetcher — local MCP environment

This backend stores cached snapshots of Reddit subreddits, posts, and comment trees to serve two read-only fetch tools with predictable performance and rate-limit protection. Main workflows: record fetch jobs (hot threads or post content), upsert subreddit/post/comment data from Reddit, and serve responses from the latest successful snapshots while tracking request history.

Repository: https://github.com/ruradium/mcp-reddit
Homepage: https://smithery.ai/server/@ruradium/mcp-reddit

## Datastore

- `subreddits.json` — Canonical subreddit records and lightweight metadata used to resolve subreddit names and cache hot listings. (18 rows; fields: ['id', 'name', 'title', 'reddit_fullname', 'nsfw', 'status', 'last_hot_fetch_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'banned', 'quarantined', 'private', 'not_found']
  - constraint: unique(lower(name))
  - constraint: name length between 1 and 21
  - constraint: name matches regex ^[A-Za-z0-9_]+$
  - constraint: updated_at >= created_at
- `posts.json` — Reddit post (thread) records, keyed by Reddit post id, used for hot listings and detailed post fetch. (19 rows; fields: ['id', 'subreddit_id', 'reddit_id', 'reddit_fullname', 'permalink', 'url', 'title', 'author', 'selftext', 'score', 'num_comments', 'over_18', 'spoiler', 'locked', 'status', 'posted_at', 'last_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed', 'deleted', 'not_found']
  - constraint: unique(reddit_id)
  - constraint: foreign key (subreddit_id) references subreddits(id) on delete restrict
  - constraint: score >= 0
  - constraint: num_comments >= 0
- `comments.json` — Materialized comment tree nodes for a post. Used to render a comment tree up to requested limits/depths. (16 rows; fields: ['id', 'post_id', 'reddit_id', 'reddit_fullname', 'parent_comment_id', 'author', 'body', 'score', 'depth', 'status', 'commented_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed', 'deleted', 'not_found']
  - constraint: unique(reddit_id)
  - constraint: foreign key (post_id) references posts(id) on delete cascade
  - constraint: foreign key (parent_comment_id) references comments(id) on delete cascade
  - constraint: depth >= 0
- `fetch_jobs.json` — Append-only job log for tool invocations that fetch/refresh subreddit hot listings or post content/comments. Supports caching, retries, and observability. (18 rows; fields: ['id', 'job_type', 'subreddit_id', 'post_id', 'requested_subreddit', 'requested_post_reddit_id', 'limit', 'comment_limit', 'comment_depth', 'status', 'cache_hit', 'http_status', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: ((job_type = 'fetch_reddit_hot_threads' and requested_subreddit is not null and limit is not null and requested_post_reddit_id is null and comment_limit is null and comment_depth is null) or (job_type = 'fetch_reddit_post_content' and requested_post_reddit_id is not null and comment_limit is not null and comment_depth is not null and requested_subreddit is null and limit is null))
  - constraint: limit between 1 and 100
  - constraint: comment_limit between 0 and 500
  - constraint: comment_depth between 0 and 10

## Business rules enforced by the tools

- fetch_reddit_hot_threads(subreddit, limit): lookup subreddits by lower(name)=lower(subreddit); if not found, create with status=active and name=subreddit (validated) before fetching; create a fetch_jobs row with job_type='fetch_reddit_hot_threads', requested_subreddit, limit, status='queued'.
- fetch_reddit_post_content(post_id, comment_limit, comment_depth): resolve posts by reddit_id=post_id; if not found, create a placeholder posts row with status=active, reddit_id=post_id and a nullable subreddit_id is NOT allowed—therefore the implementation must first fetch minimal post metadata from Reddit to determine subreddit and upsert subreddits/posts before marking job running.
- Hot threads caching: if subreddits.last_hot_fetch_at is within a configured TTL (e.g., 120s), the service may set fetch_jobs.cache_hit=true and return posts for that subreddit ordered by score/posted_at from the last snapshot without contacting Reddit.
- Post content caching: if posts.last_fetched_at is within a configured TTL (e.g., 300s), the service may set fetch_jobs.cache_hit=true and return the post plus comments from cache without contacting Reddit.
- When fetching hot threads, the system upserts posts by unique(reddit_id) and ensures posts.subreddit_id matches the subreddit fetched; conflicts must be resolved by updating subreddit_id to the latest authoritative value from Reddit.
- When fetching post content, the system upserts the posts row fields (title, selftext, score, num_comments, flags, status) and upserts comments by unique(reddit_id), setting parent_comment_id where known; comments.depth must not exceed the requested comment_depth when materializing the response.
- For fetch_reddit_post_content responses, the returned comment tree must include at most comment_limit top-level comments (depth=0) and may include descendants up to comment_depth, filtered to the same posts.id.
- Job lifecycle enforcement: fetch_jobs.status must follow the declared transitions; setting status to succeeded/failed/cancelled must set finished_at, and setting status to running must set started_at.
- Rate limiting/upstream failures: if Reddit returns 429/5xx, record fetch_jobs.http_status and set status='failed'; do not partially update last_hot_fetch_at/last_fetched_at unless the fetch completes successfully.