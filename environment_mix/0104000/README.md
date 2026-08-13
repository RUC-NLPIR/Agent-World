# LeetCode — local MCP environment

This backend mirrors key LeetCode read APIs by caching problem metadata/content, daily challenge selection, user profiles and activity, and community solution topics/articles. Main workflows: periodically ingest/update problems and daily challenge, fetch user profile + submissions + contest ranking on demand (with caching), and index/list solution metadata then fetch full solution content by topicId.

Repository: https://github.com/jinzcdev/leetcode-mcp-server
Homepage: https://smithery.ai/server/@jinzcdev/leetcode-mcp-server

## Datastore

- `problems.json` — Canonical LeetCode problem catalog with full detail needed for get_problem, get_daily_challenge, and search_problems. (20 rows; fields: ['id', 'title_slug', 'frontend_question_id', 'title', 'category', 'difficulty', 'is_paid_only', 'problem_html', 'constraints_html', 'examples_json', 'hints_json', 'tags', 'status', 'source_last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'hidden']
  - constraint: unique(title_slug)
  - constraint: frontend_question_id is unique where not null
  - constraint: difficulty in ('EASY','MEDIUM','HARD')
  - constraint: category in ('all-code-essentials','algorithms','database','pandas','javascript','shell','concurrency')
- `daily_challenges.json` — Tracks the Daily Challenge selection by date and ties it to a problem for get_daily_challenge. (19 rows; fields: ['id', 'challenge_date', 'problem_id', 'status', 'source_payload_json', 'source_last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['published', 'superseded']
  - constraint: unique(challenge_date) where status='published'
  - constraint: problem_id must reference problems.id
  - constraint: at most one published record per day
- `users.json` — Cached LeetCode user profiles used by get_user_profile and as parent entity for submissions and contest ranking. (18 rows; fields: ['id', 'username', 'display_name', 'avatar_url', 'country', 'profile_json', 'stats_json', 'status', 'source_last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'not_found', 'disabled']
  - constraint: unique(username)
  - constraint: username length between 1 and 64
  - constraint: status in ('active','not_found','disabled')
- `submissions.json` — Recent user submissions (accepted and failed) used by get_recent_submissions and get_recent_ac_submissions. (18 rows; fields: ['id', 'user_id', 'problem_id', 'source_submission_id', 'lang', 'status', 'runtime_ms', 'memory_kb', 'submitted_at', 'source_payload_json', 'created_at', 'updated_at'])
  - lifecycle `status`: ['AC', 'WA', 'TLE', 'MLE', 'RE', 'CE', 'SKIPPED', 'UNKNOWN']
  - constraint: unique(user_id, source_submission_id)
  - constraint: user_id must reference users.id
  - constraint: problem_id must reference problems.id when not null
  - constraint: runtime_ms >= 0 when not null
- `contest_rankings.json` — Cached contest ranking and participation history per user used by get_user_contest_ranking, with optional filtering for attended contests. (18 rows; fields: ['id', 'user_id', 'attended_only', 'ranking_json', 'status', 'source_last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'error']
  - constraint: unique(user_id, attended_only)
  - constraint: user_id must reference users.id
- `solutions.json` — Community solution topics/articles, supporting list_problem_solutions (metadata list) and get_problem_solution (full content by topicId). (20 rows; fields: ['id', 'topic_id', 'problem_id', 'title', 'author_username', 'tags', 'vote_count', 'is_pinned', 'published_at', 'content_html', 'navigation_json', 'status', 'source_last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['metadata_only', 'fetched', 'removed']
  - constraint: unique(topic_id)
  - constraint: problem_id must reference problems.id
  - constraint: vote_count >= 0 when not null
  - constraint: if status='fetched' then content_html is not null

## Business rules enforced by the tools

- get_problem(titleSlug) must resolve problems.title_slug = titleSlug and return full detail fields (problem_html, constraints_html, examples_json, hints_json, tags, difficulty, category) when present; if not present or status != 'active', return not found or appropriate error.
- search_problems(category, tags, difficulty, searchKeywords, limit, offset) queries problems where status='active', filters by category if provided, difficulty if provided, and requires that each requested tag is contained in problems.tags (AND semantics) unless the API chooses OR semantics explicitly; results are paginated by limit/offset.
- search_problems.limit must be an integer between 1 and 100; offset must be an integer >= 0.
- get_daily_challenge() must select the daily_challenges row for the current UTC date where status='published' and join to problems; if missing, it may trigger a sync job but must not return a different date's published row.
- get_user_profile(username) must upsert into users by unique(username); on upstream 404-like response set users.status='not_found' and avoid creating child submission/ranking rows for that username until status returns to 'active'.
- get_recent_submissions(username, limit) must resolve users.username then fetch from submissions where user_id matches, ordered by submitted_at desc; limit must be integer between 1 and 50.
- get_recent_ac_submissions(username, limit) is identical to get_recent_submissions but additionally filters submissions.status='AC'.
- get_user_contest_ranking(username, attended) must resolve users.username then read contest_rankings by (user_id, attended_only=attended); if cache is stale/error it may refresh and update ranking_json and status accordingly.
- list_problem_solutions(questionSlug, limit, skip, orderBy, userInput, tagSlugs) must resolve problems.title_slug=questionSlug then query solutions.problem_id; apply skip/limit with skip>=0 and limit between 1 and 50; filter by tagSlugs such that returned solutions have at least one overlap with solutions.tags; userInput performs case-insensitive match against solutions.title and author_username and may also search within content_html when status='fetched'.
- list_problem_solutions.orderBy must map to a deterministic sort: 'HOT' sorts by a weighted score (e.g., pinned desc, vote_count desc, published_at desc), 'MOST_VOTES' by vote_count desc then published_at desc, 'MOST_RECENT' by published_at desc; invalid values are rejected.
- get_problem_solution(topicId) must lookup solutions.topic_id=topicId; if status='metadata_only' it should fetch and populate content_html/navigation_json and transition to 'fetched'; if upstream indicates deletion, transition to 'removed'.
- Foreign key integrity must be enforced: daily_challenges.problem_id and solutions.problem_id require corresponding problems rows; submissions.user_id requires users row; submissions.problem_id when present requires problems row.
- All created_at/updated_at fields are set by the system; updated_at must change on any mutation including cache refresh and status transitions.