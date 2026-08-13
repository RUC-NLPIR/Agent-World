# 小红书 MCP 服务 xiaohongshu — local MCP environment

该后端为“小红书 MCP 服务”提供会话级 Cookie 管理、搜索与内容抓取的缓存层，以及评论发布与审计。主要流程包括：检查/刷新可用 Cookie 会话；拉取首页 feed、按关键词搜索笔记并缓存结果；按带 xsec_token 的 url 抓取笔记正文与评论；使用有效会话对指定笔记发布评论并记录结果与失败原因。

Repository: https://github.com/jobsonlook/xhs-mcp
Homepage: https://smithery.ai/server/@jobsonlook/xhs-mcp

## Datastore

- `cookie_sessions.json` — 存储用于访问小红书的 Cookie 会话（含有效性检测、失效原因、轮换与风控信息），供所有需要登录态的工具调用。 (11 rows; fields: ['id', 'label', 'cookie_jar', 'user_id_hint', 'last_checked_at', 'last_check_ok', 'last_check_error', 'risk_score', 'status', 'disabled_reason', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'limited', 'expired', 'banned', 'disabled']
  - constraint: risk_score >= 0 and risk_score <= 1
  - constraint: last_check_ok = true implies status in ('active','limited')
  - constraint: status in ('expired','banned') implies last_check_ok = false
  - constraint: if status='disabled' then disabled_reason is not null
- `notes.json` — 笔记主表：从搜索/feed/内容抓取中归档的笔记元数据与正文摘要，支持按 url(note url + xsec_token) 追溯与缓存。 (30 rows; fields: ['id', 'platform_note_id', 'canonical_url', 'tokenized_url', 'xsec_token', 'title', 'author_platform_id', 'author_name', 'content_text', 'content_raw', 'last_content_fetched_at', 'last_comments_fetched_at', 'visibility', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['discovered', 'fetched', 'stale', 'blocked']
  - constraint: unique(platform_note_id)
  - constraint: unique(tokenized_url) where tokenized_url is not null
  - constraint: visibility in ('unknown','public','restricted','deleted')
  - constraint: if tokenized_url is not null then xsec_token is not null
- `search_queries.json` — 搜索与首页 feed 的请求归档与结果缓存索引。用于 search_notes 与 home_feed 的去重、限频、可观测性。 (39 rows; fields: ['id', 'type', 'keywords', 'request_fingerprint', 'cookie_session_id', 'status', 'http_status', 'error_code', 'error_message', 'result_count', 'raw_response', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: unique(type, request_fingerprint)
  - constraint: type='search_notes' implies keywords is not null
  - constraint: type='home_feed' implies keywords is null
  - constraint: result_count is null or result_count >= 0
- `query_note_results.json` — 查询结果明细（search_notes/home_feed 返回的笔记列表），用于结果分页/排序回放与缓存命中。 (35 rows; fields: ['id', 'search_query_id', 'note_id', 'rank', 'snippet', 'cover_url', 'extra', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active']
  - constraint: unique(search_query_id, rank)
  - constraint: unique(search_query_id, note_id)
  - constraint: rank >= 1
  - constraint: search_query_id references search_queries.id on delete cascade
- `note_comments.json` — 笔记评论缓存与发布记录（含上游评论ID、作者信息、层级关系）。同时承载 get_note_comments 的返回与 post_comment 的审计。 (31 rows; fields: ['id', 'note_id', 'platform_comment_id', 'parent_platform_comment_id', 'author_platform_id', 'author_name', 'content', 'source', 'posted_by_cookie_session_id', 'status', 'post_error_code', 'post_error_message', 'commented_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['visible', 'pending_post', 'post_succeeded', 'post_failed', 'deleted']
  - constraint: content length between 1 and 500
  - constraint: source='posted' implies posted_by_cookie_session_id is not null
  - constraint: source='fetched' implies posted_by_cookie_session_id is null
  - constraint: unique(note_id, platform_comment_id) where platform_comment_id is not null

## Business rules enforced by the tools

- check_cookie 工具：必须选择一个 status in ('active','limited') 的 cookie_sessions 进行探测；探测成功则写入 last_checked_at、last_check_ok=true，并将 status 置为 active 或 limited；探测失败则写入 last_check_ok=false、last_check_error，并按错误类型将 status 置为 expired/banned/limited（风控）。
- home_feed 工具：创建一条 search_queries(type='home_feed') 记录并进入 queued->running；成功后写 raw_response、result_count，并将返回的每条笔记 upsert 到 notes（按 platform_note_id 或 tokenized_url 去重），再写入 query_note_results(rank...)。
- search_notes 工具：必须提供非空 keywords（尽管 tool schema 未声明参数，服务端仍需校验）；创建 search_queries(type='search_notes', keywords=...) 并生成 request_fingerprint=hash(type+keywords)；对相同 fingerprint 的已成功查询在 TTL 内可直接复用其 query_note_results。
- get_note_content 工具：入参 url 必须包含 xsec_token；服务端先按 notes.tokenized_url 命中缓存，若 last_content_fetched_at 在 TTL 内则直接返回 notes.content_*；否则用有效 cookie_session 抓取并更新 notes.content_raw/content_text、last_content_fetched_at，并将 notes.status 置为 fetched。
- get_note_comments 工具：入参 url 必须包含 xsec_token；服务端解析/关联 notes（按 tokenized_url 或 platform_note_id）；若 last_comments_fetched_at 在 TTL 内则返回 note_comments where note_id=? and status in ('visible','post_succeeded')；否则抓取并 upsert fetched 来源的评论到 note_comments，然后更新 notes.last_comments_fetched_at。
- post_comment 工具：必须校验 note_id 对应 notes.platform_note_id 存在；创建 note_comments(source='posted', status='pending_post', content=comment, posted_by_cookie_session_id=...)；调用上游发布成功后回填 platform_comment_id、commented_at，并置 status='post_succeeded'（随后可异步转为 visible）；失败则置 status='post_failed' 并写 post_error_*。
- 所有写入必须维护外键完整性：query_note_results.search_query_id 必须存在，query_note_results.note_id 必须存在；note_comments.note_id 必须存在。
- 限流/配额：当某 cookie_sessions.status='limited' 或 risk_score>0.7 时，同一会话每分钟最多执行 30 次上游请求（实现可通过 request_fingerprint 去重与队列层完成，但必须在 search_queries 写入失败原因）。
- 数据保留：search_queries 与 query_note_results 可按 created_at 进行 TTL 清理（例如 7-30 天）；清理 search_queries 时必须级联删除 query_note_results；notes 与 note_comments 可长期保留以提高缓存命中。