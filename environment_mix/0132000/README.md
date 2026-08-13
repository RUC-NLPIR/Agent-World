# RedNote Content Access Server — local MCP environment

该后端为“RedNote Content Access Server”提供数据支撑：维护登录会话（用于访问/抓取小红书内容）、缓存已获取的笔记与评论，并记录搜索请求与返回结果以加速后续查询与审计。主要流程为：login 创建/刷新会话；search_notes 记录查询并返回命中笔记；get_note_content / get_note_comments 依据 URL 查找或触发抓取并读取缓存内容。

Repository: https://github.com/JonaFly/RedNote-MCP
Homepage: https://smithery.ai/server/@JonaFly/rednote-mcp

## Datastore

- `accounts.json` — 被登录的小红书账号实体（服务侧管理的账号壳）。login 工具会创建/激活一个账号并关联一个会话。 (12 rows; fields: ['id', 'platform', 'username', 'phone_masked', 'status', 'last_login_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'locked', 'disabled']
  - constraint: unique(platform, username) WHERE username IS NOT NULL
  - constraint: unique(platform, phone_masked) WHERE phone_masked IS NOT NULL
- `auth_sessions.json` — 登录产生的会话/凭证（cookie/令牌等）的持久化。login 工具会创建或刷新一条 active 会话。 (12 rows; fields: ['id', 'account_id', 'status', 'cookie_jar_encrypted', 'user_agent', 'ip_address', 'last_verified_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'revoked']
  - constraint: fk(account_id) references accounts(id) on delete cascade
  - constraint: unique(account_id) WHERE status = 'active'
  - constraint: expires_at IS NULL OR expires_at >= created_at
- `notes.json` — 笔记基础信息与正文内容缓存。get_note_content 通过 url 查找该表；search_notes 主要在该表做关键词检索（标题/正文/作者等）。 (19 rows; fields: ['id', 'platform', 'url', 'note_key', 'author_name', 'title', 'content_text', 'content_html', 'media_urls', 'tags', 'published_at', 'status', 'last_fetched_at', 'fetch_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['discovered', 'fetching', 'available', 'unavailable', 'deleted']
  - constraint: unique(platform, url)
  - constraint: unique(platform, note_key) WHERE note_key IS NOT NULL
- `comments.json` — 笔记评论缓存。get_note_comments 通过 url -> notes.id 再读取该表。 (30 rows; fields: ['id', 'note_id', 'platform_comment_id', 'parent_comment_id', 'author_name', 'content_text', 'like_count', 'commented_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['visible', 'deleted', 'hidden']
  - constraint: fk(note_id) references notes(id) on delete cascade
  - constraint: unique(note_id, platform_comment_id) WHERE platform_comment_id IS NOT NULL
  - constraint: like_count >= 0
- `search_queries.json` — search_notes 调用记录与结果关联（用于审计、限流、缓存与改进召回）。keywords 与 limit 参数映射到本表字段。 (18 rows; fields: ['id', 'keywords', 'limit', 'status', 'executed_at', 'result_count', 'error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'completed', 'failed']
  - constraint: limit >= 1 AND limit <= 50
  - constraint: result_count >= 0
- `search_query_results.json` — search_notes 的查询结果明细（一个查询对应多条笔记命中）。用于稳定复现返回与缓存分页。 (32 rows; fields: ['id', 'query_id', 'note_id', 'rank', 'score', 'snippet', 'created_at', 'updated_at'])
  - constraint: fk(query_id) references search_queries(id) on delete cascade
  - constraint: fk(note_id) references notes(id) on delete restrict
  - constraint: unique(query_id, rank)
  - constraint: unique(query_id, note_id)

## Business rules enforced by the tools

- login 必须创建或刷新一条 auth_sessions 记录，并保证同一 account_id 同时最多只有一个 status='active' 的会话；若存在 active 会话则更新其 cookie_jar_encrypted、updated_at、last_verified_at。
- search_notes(keywords, limit) 必须写入 search_queries.keywords 与 search_queries.limit（未提供 limit 时使用默认值 10），并将 limit 归一化为整数且限制在 [1, 50]。
- search_notes 在 search_queries.status 上必须遵循 queued->running->completed/failed 的状态流转，completed 时必须填充 result_count 并写入 search_query_results（rank 从1递增且不超过 limit）。
- get_note_content(url) 必须通过 notes.url 精确匹配定位笔记；若不存在则创建 notes 记录（status='discovered'），随后进入 fetching 并在成功后置为 available，失败置为 unavailable 并记录 fetch_error。
- get_note_comments(url) 必须先通过 notes.url 定位 notes.id；若 notes 不存在需先创建 discovered 记录；评论写入 comments 时若提供 platform_comment_id 则必须满足 (note_id, platform_comment_id) 唯一以保证幂等。
- comments.like_count 必须为非负整数；notes.url 必须在同一 platform 下唯一；notes.note_key 若存在也必须在同一 platform 下唯一。
- 当 notes.status='deleted' 时，不允许将其重新置为 available；当 auth_sessions.status='revoked' 时不允许重新激活。