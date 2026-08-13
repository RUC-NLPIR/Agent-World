# Reddit MCP — local MCP environment

This backend stores cached Reddit entities (subreddits, submissions, comments) and a record of search requests made through the MCP tools. The main workflows are: read-through caching on entity fetch tools (get_submission/get_subreddit/get_comment/get_comments_by_submission) and persisting normalized search queries plus their result sets for search_posts/search_subreddits.

Repository: https://github.com/GridfireAI/reddit-mcp
Homepage: https://smithery.ai/server/@GridfireAI/reddit-mcp

## Datastore

- `subreddits.json` — Canonical subreddit records, keyed by Reddit fullname and name, used by get_subreddit and as a foreign key for submissions and search filters. (18 rows; fields: ['id', 'name', 'title', 'public_description', 'description', 'subscribers', 'over18', 'lang', 'url', 'icon_img', 'community_icon', 'retrieval_status', 'last_fetched_at', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `retrieval_status`: ['fresh', 'stale', 'missing', 'error']
  - constraint: unique(lower(name))
  - constraint: subscribers is null or subscribers >= 0
  - constraint: name matches /^[A-Za-z0-9_]{2,21}$/
  - constraint: retrieval_status in ('fresh','stale','missing','error')
- `submissions.json` — Reddit post/submission records used by get_submission and returned by search_posts. (19 rows; fields: ['id', 'subreddit_id', 'subreddit_name', 'title', 'selftext', 'author', 'created_utc', 'permalink', 'url', 'is_self', 'nsfw', 'locked', 'num_comments', 'score', 'upvote_ratio', 'retrieval_status', 'last_fetched_at', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `retrieval_status`: ['fresh', 'stale', 'missing', 'error']
  - constraint: foreign key (subreddit_id) references subreddits(id) on delete set null
  - constraint: num_comments is null or num_comments >= 0
  - constraint: upvote_ratio is null or (upvote_ratio >= 0 and upvote_ratio <= 1)
  - constraint: retrieval_status in ('fresh','stale','missing','error')
- `comments.json` — Reddit comment records used by get_comment_by_id and get_comments_by_submission, including threaded relationships. (18 rows; fields: ['id', 'submission_id', 'parent_comment_id', 'subreddit_id', 'author', 'body', 'created_utc', 'score', 'permalink', 'is_submitter', 'retrieval_status', 'last_fetched_at', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `retrieval_status`: ['fresh', 'stale', 'missing', 'error']
  - constraint: foreign key (submission_id) references submissions(id) on delete cascade
  - constraint: foreign key (parent_comment_id) references comments(id) on delete set null
  - constraint: foreign key (subreddit_id) references subreddits(id) on delete set null
  - constraint: id like 't1_%'
- `search_requests.json` — Normalized record of searches performed via search_posts and search_subreddits, including raw parameters and execution status for observability and caching. (19 rows; fields: ['id', 'tool_name', 'subreddit_name', 'subreddit_id', 'query', 'search_mode', 'raw_params', 'limit', 'sort', 'time_filter', 'status', 'started_at', 'completed_at', 'error_message', 'result_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: tool_name in ('search_posts','search_subreddits')
  - constraint: status in ('queued','running','succeeded','failed')
  - constraint: limit is null or (limit >= 1 and limit <= 100)
  - constraint: result_count is null or result_count >= 0
- `search_results.json` — Stores per-request ranked results for searches; links search_requests to either submissions or subreddits. (18 rows; fields: ['id', 'search_request_id', 'rank', 'entity_type', 'submission_id', 'subreddit_id', 'score', 'snippet', 'raw_item', 'created_at', 'updated_at'])
  - lifecycle `entity_type`: ['submission', 'subreddit']
  - constraint: foreign key (search_request_id) references search_requests(id) on delete cascade
  - constraint: foreign key (submission_id) references submissions(id) on delete cascade
  - constraint: foreign key (subreddit_id) references subreddits(id) on delete cascade
  - constraint: rank >= 1

## Business rules enforced by the tools

- get_subreddit(name) must resolve case-insensitively by subreddits.name; on cache miss it must create a row with retrieval_status='missing', then attempt fetch and update to 'fresh' or 'error' with error_message.
- get_submission(submission_id) must accept either fullname (t3_*) or base36 id; base36 must be normalized to fullname before lookup/storage. Cached rows transition fresh->stale based on TTL and are refetched on read when stale.
- get_comment_by_id(comment_id) must accept either fullname (t1_*) or base36 id; base36 must be normalized to fullname before lookup/storage. If replies are fetched, parent_comment_id must be set for each reply and submission_id must be populated.
- get_comments_by_submission(submission_id, replace_more) must ensure all returned comments have comments.submission_id = submissions.id. If replace_more=true, the service must attempt to hydrate missing nested comments and set retrieval_status accordingly; if false, it may omit unresolved placeholders without creating comment rows.
- search_posts(params) must insert a search_requests row with tool_name='search_posts', store all provided args in raw_params, and enforce limit <= 100 when a limit is provided; results must be written to search_results with entity_type='submission' and monotonically increasing rank starting at 1.
- search_subreddits(by) must insert a search_requests row with tool_name='search_subreddits' and search_mode set to 'by_name' or 'by_description' (derived from 'by'); results must be written to search_results with entity_type='subreddit' and monotonically increasing rank starting at 1.
- For any search_request, search_results must be deleted automatically when the parent search_request is deleted (cascade), and result_count on search_requests must equal the number of child search_results rows after completion.
- FK integrity: comments.submission_id must reference an existing submissions row; if a comment is fetched for an unknown submission, the service must upsert the submission shell row (retrieval_status='missing') before inserting the comment.
- Uniqueness: subreddits.name must be globally unique case-insensitively; search_results(search_request_id, rank) must be unique to preserve stable ordering.