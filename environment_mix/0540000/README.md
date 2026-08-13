# Reddit Browser — local MCP environment

This backend stores cached Reddit entities (subreddits, submissions, comments) and records user search requests executed through the Reddit Browser service. The main workflows are: look up a subreddit/submission/comment by id or name, fetch and optionally hydrate comment trees for a submission, and run/search-log post and subreddit searches with filters and paging while reusing cached objects.

Repository: https://github.com/geobio/reddit-mcp
Homepage: https://smithery.ai/server/@geobio/reddit-mcp

## Datastore

- `subreddits.json` — Canonical cache of subreddit metadata keyed by Reddit's subreddit name, used by get_subreddit and search_subreddits results. (18 rows; fields: ['id', 'reddit_fullname', 'name', 'title', 'public_description', 'description', 'over18', 'subscribers', 'url', 'icon_img', 'community_icon', 'lang', 'status', 'last_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'banned', 'quarantined', 'restricted', 'archived']
  - constraint: unique(lower(name))
  - constraint: reddit_fullname is unique when not null
  - constraint: subscribers >= 0 when not null
  - constraint: status in ('active','banned','quarantined','restricted','archived')
- `submissions.json` — Cached Reddit submissions (posts). Serves get_submission and search_posts results; links to subreddits. (20 rows; fields: ['id', 'reddit_id', 'reddit_fullname', 'subreddit_id', 'subreddit_name', 'title', 'selftext', 'url', 'permalink', 'author', 'is_self', 'over_18', 'spoiler', 'locked', 'stickied', 'score', 'num_comments', 'created_utc', 'status', 'last_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'removed', 'archived']
  - constraint: unique(reddit_id)
  - constraint: reddit_fullname is unique when not null
  - constraint: foreign key (subreddit_id) references subreddits(id) on update cascade on delete restrict
  - constraint: score >= 0 when not null
- `comments.json` — Cached Reddit comments with parent-child relationships. Powers get_comment_by_id and get_comments_by_submission (including replies). (18 rows; fields: ['id', 'reddit_id', 'reddit_fullname', 'submission_id', 'subreddit_id', 'parent_comment_id', 'parent_kind', 'depth', 'author', 'body', 'score', 'created_utc', 'status', 'last_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'removed', 'archived']
  - constraint: unique(reddit_id)
  - constraint: reddit_fullname is unique when not null
  - constraint: foreign key (submission_id) references submissions(id) on update cascade on delete cascade
  - constraint: foreign key (subreddit_id) references subreddits(id) on update cascade on delete restrict
- `search_requests.json` — Audit log and cache key for search_posts and search_subreddits, including query parameters, paging, and execution metadata. Also supports tracing read tools even when parameters are empty in the exposed schema. (18 rows; fields: ['id', 'tool_name', 'request_fingerprint', 'params', 'subreddit_id', 'submission_id', 'comment_id', 'status', 'result_count', 'error_message', 'cache_hit', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: unique(tool_name, request_fingerprint)
  - constraint: foreign key (subreddit_id) references subreddits(id) on update cascade on delete set null
  - constraint: foreign key (submission_id) references submissions(id) on update cascade on delete set null
  - constraint: foreign key (comment_id) references comments(id) on update cascade on delete set null
- `search_results.json` — Join table between search_requests and returned entities, preserving ordering and enabling replay/caching of search responses for search_posts and search_subreddits (and optionally comment listing responses). (18 rows; fields: ['id', 'search_request_id', 'entity_type', 'subreddit_id', 'submission_id', 'comment_id', 'rank', 'score_hint', 'created_at', 'updated_at'])
  - constraint: foreign key (search_request_id) references search_requests(id) on update cascade on delete cascade
  - constraint: foreign key (subreddit_id) references subreddits(id) on update cascade on delete cascade
  - constraint: foreign key (submission_id) references submissions(id) on update cascade on delete cascade
  - constraint: foreign key (comment_id) references comments(id) on update cascade on delete cascade

## Business rules enforced by the tools

- get_subreddit must resolve by exact name case-insensitively; if not found or stale (now - last_fetched_at > TTL), fetch from Reddit, upsert subreddits by lower(name), and update last_fetched_at.
- get_submission must resolve by reddit_id (base36) and upsert submissions.unique(reddit_id); it must also ensure the referenced subreddit exists (create/update subreddits row first) and enforce FK integrity.
- get_comment_by_id must resolve by comment reddit_id and return the comment plus its reply subtree by following comments.parent_comment_id; recursion depth must be bounded by a service limit (e.g., max_depth) to prevent unbounded traversal.
- get_comments_by_submission must resolve the submission by reddit_id; when replace_more=true it must hydrate additional comments and upsert into comments, ensuring parent_kind/parent_comment_id consistency and depth>=0.
- search_posts must require a subreddit target in params (subreddit_name) and store normalized params (query, sort, time_filter, limit, after/before) in search_requests.params; it must write ordered results to search_results with entity_type='submission' and rank contiguous from 0.
- search_subreddits must store which mode was used (by=name vs by=description) inside search_requests.params, and persist returned subreddits into subreddits (upsert by lower(name)) before inserting search_results rows.
- For all tools, a search_requests row must be created with status queued->running->(succeeded|failed); failed requests must persist error_message; succeeded requests must set result_count equal to the number of search_results rows (or 1 for direct gets).
- Caching: if a request_fingerprint already exists with status=succeeded and is within TTL, the service may set cache_hit=true and reuse existing search_results; otherwise cache_hit=false and it must refresh entities and rewrite results (new search_request row or update policy must be consistent with unique(tool_name, request_fingerprint)).
- Deletion/removed semantics: if Reddit returns deleted/removed content, submissions/comments must be updated to status deleted/removed and body/selftext may be nulled; transitions must follow the declared lifecycle transitions.