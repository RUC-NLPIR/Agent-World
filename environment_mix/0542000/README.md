# WSB Analyst — local MCP environment

WSB Analyst stores snapshots of r/wallstreetbets posts and their enriched details (comments, extracted links), plus cached trending ticker pulls from ApeWisdom. The main workflows are: periodically/ondemand fetch top posts, hydrate post details in batches with a short-lived cache, and compute derived outputs like external link sets and trending tickers while tracking request provenance.

Repository: https://github.com/ferdousbhai/wsb-analyst-mcp
Homepage: https://smithery.ai/server/@ferdousbhai/wsb-analyst-mcp

## Datastore

- `post_summaries.json` — Lightweight snapshots of top WSB posts as returned by listing-style endpoints (e.g., hot/top). Used by find_top_posts and as the candidate set for filtered fetches. (18 rows; fields: ['id', 'reddit_post_id', 'subreddit', 'title', 'author', 'flair', 'permalink', 'url', 'is_self', 'score', 'num_comments', 'created_utc', 'status', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed', 'deleted', 'archived']
  - constraint: unique(reddit_post_id)
  - constraint: score >= 0
  - constraint: num_comments >= 0
  - constraint: subreddit = 'wallstreetbets' OR subreddit IS NOT NULL
- `post_details_cache.json` — Hydrated, detailed post payloads (including top comments and extracted links) with a 5-minute TTL cache. Serves fetch_post_details, fetch_batch_post_details, and fetch_detailed_wsb_posts. (18 rows; fields: ['id', 'post_id', 'reddit_post_id', 'selftext', 'media', 'top_comments', 'extracted_links', 'fetched_at', 'expires_at', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'error']
  - constraint: unique(post_id) WHERE status IN ('fresh','stale','error')
  - constraint: unique(reddit_post_id) WHERE status IN ('fresh','stale','error')
  - constraint: expires_at > fetched_at
  - constraint: json_array(top_comments)
- `post_external_links.json` — Normalized mapping of extracted external links per post details fetch. Enables fast unique link aggregation for get_external_links without re-parsing cached blobs. (17 rows; fields: ['id', 'details_id', 'post_id', 'url', 'host', 'source', 'first_seen_at', 'created_at', 'updated_at'])
  - lifecycle `source`: ['post', 'comment']
  - constraint: unique(post_id, url)
  - constraint: url LIKE 'http%'
- `apewisdom_trending_runs.json` — Represents one pull/run of trending tickers from ApeWisdom for a given filter and requested size. Used by get_top_trending_tickers and to retain auditability of computed results. (18 rows; fields: ['id', 'filter', 'num_stocks_requested', 'status', 'source_url', 'started_at', 'finished_at', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['running', 'succeeded', 'failed']
  - constraint: num_stocks_requested BETWEEN 1 AND 200
  - constraint: filter <> ''
  - constraint: finished_at IS NULL OR finished_at >= started_at
- `apewisdom_trending_tickers.json` — Tickers returned by an ApeWisdom trending run, including raw metrics and whether they passed NASDAQ symbol validation. get_top_trending_tickers returns the top valid tickers for the most recent run matching inputs. (17 rows; fields: ['id', 'run_id', 'symbol', 'rank', 'mentions', 'upvotes', 'is_valid_nasdaq_symbol', 'validation_source', 'created_at', 'updated_at'])
  - lifecycle `is_valid_nasdaq_symbol`: ['true', 'false']
  - constraint: unique(run_id, symbol)
  - constraint: unique(run_id, rank)
  - constraint: rank >= 1
  - constraint: mentions IS NULL OR mentions >= 0

## Business rules enforced by the tools

- find_top_posts returns the most recently seen post_summaries for subreddit='wallstreetbets', ordered by last_seen_at desc then score desc; it upserts by reddit_post_id and updates score/num_comments/flair/title/last_seen_at.
- fetch_post_details takes a reddit post id (post_id in tool docs): resolve to post_summaries by reddit_post_id; if missing, create a minimal post_summaries row with status='active' and last_seen_at=now before hydrating details.
- fetch_post_details must return cached details when post_details_cache.status='fresh' and expires_at > now; otherwise it must refetch, overwrite the cache row (same post_id), set fetched_at=now, expires_at=now+5 minutes, and status='fresh' on success or status='error' with error_message on failure.
- fetch_batch_post_details accepts a list of reddit_post_id values; it processes each independently using the same caching semantics as fetch_post_details and returns a dictionary keyed by reddit_post_id.
- fetch_detailed_wsb_posts filters candidates from post_summaries where score >= min_score AND num_comments >= min_comments AND (flair IS NULL OR flair NOT IN excluded_flairs); it then hydrates details for up to limit posts using the same 5-minute cache policy.
- get_external_links scans up to limit posts selected using the same score/comment filters as fetch_detailed_wsb_posts, ensures details are hydrated (or uses fresh cache), and returns the de-duplicated set of post_external_links.url across those posts.
- When post_details_cache is refreshed successfully, post_external_links for that post must be replaced to match post_details_cache.extracted_links (delete missing, insert new) and set first_seen_at for newly inserted links.
- get_top_trending_tickers creates an apewisdom_trending_runs row with status='running', fetches ApeWisdom data for (filter, num_stocks_requested), inserts apewisdom_trending_tickers rows, marks each row is_valid_nasdaq_symbol based on the service's NASDAQ symbol list, then transitions the run to status='succeeded' (or 'failed' with error_message).
- get_top_trending_tickers returns symbols from the most recent succeeded run matching (filter, num_stocks_requested) if it exists and is recent enough per service cache policy; otherwise it performs a new run. Only is_valid_nasdaq_symbol=true tickers are returned, ordered by rank asc, limited to num_stocks_requested.
- All FK references must be enforced: post_details_cache.post_id must exist in post_summaries; post_external_links.details_id must exist in post_details_cache; apewisdom_trending_tickers.run_id must exist in apewisdom_trending_runs.
- Status transitions must follow the declared lifecycles; invalid transitions are rejected (e.g., apewisdom_trending_runs cannot move from succeeded back to running).