# Trends Hub — local MCP environment

Trends Hub 聚合多个内容源（新闻站点、社区、短视频与榜单服务）的“热榜/榜单/最新资讯”，并对外提供统一的读取 API。后端核心工作流是：定时抓取或按需拉取各来源 -> 归一化存储条目与榜单快照 -> 记录每次 API 调用与抓取运行情况以便缓存、审计与限流。

Repository: https://github.com/baranwang/mcp-trends-hub
Homepage: https://smithery.ai/server/@baranwang/mcp-trends-hub

## Datastore

- `sources.json` — 内容来源与其可用端点/榜单类型配置（例如 BBC、36kr、Bilibili、NYTimes 等），用于驱动抓取与参数校验。 (21 rows; fields: ['id', 'slug', 'display_name', 'default_language', 'base_url', 'supports_params', 'cache_ttl_seconds', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'paused', 'deprecated']
  - constraint: unique(slug)
  - constraint: cache_ttl_seconds >= 10 AND cache_ttl_seconds <= 86400
  - constraint: supports_params must be valid JSON object
- `fetch_jobs.json` — 抓取/拉取运行记录。可由定时任务创建，也可在 API 读请求触发缓存失效时创建（stale-while-revalidate）。 (33 rows; fields: ['id', 'source_id', 'tool_name', 'request_params', 'cache_key', 'trigger', 'status', 'started_at', 'finished_at', 'http_status', 'error_code', 'error_message', 'items_fetched', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(source_id) references sources(id)
  - constraint: unique(cache_key, status) WHERE status IN ('queued','running')
  - constraint: items_fetched >= 0
  - constraint: http_status IS NULL OR (http_status >= 100 AND http_status <= 599)
- `trend_snapshots.json` — 某来源 + 某参数组合 在某次抓取后的榜单/列表快照元数据。读取工具优先返回最新且未过期的快照。 (33 rows; fields: ['id', 'source_id', 'fetch_job_id', 'tool_name', 'request_params', 'cache_key', 'status', 'generated_at', 'expires_at', 'item_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ready', 'stale', 'purged']
  - constraint: foreign key(source_id) references sources(id)
  - constraint: foreign key(fetch_job_id) references fetch_jobs(id)
  - constraint: unique(cache_key, generated_at)
  - constraint: item_count >= 0
- `trend_items.json` — 归一化后的内容条目（文章/视频/话题/书籍等）。同一内容可能在不同快照中重复出现，通过 canonical_key 去重。 (31 rows; fields: ['id', 'source_id', 'canonical_key', 'source_content_id', 'url', 'title', 'summary', 'author', 'language', 'published_at', 'content_type', 'raw_payload', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed', 'blocked']
  - constraint: foreign key(source_id) references sources(id)
  - constraint: unique(source_id, canonical_key)
  - constraint: title <> ''
  - constraint: url IS NULL OR url LIKE 'http%'
- `snapshot_items.json` — 快照与条目的关联表，记录每个条目在该快照内的排名/热度等榜单特征。支持分页（start/count/limit/page_size）通过对 rank 排序并 offset/limit 实现。 (30 rows; fields: ['id', 'snapshot_id', 'item_id', 'rank', 'score', 'metrics', 'extra', 'created_at', 'updated_at'])
  - constraint: foreign key(snapshot_id) references trend_snapshots(id) ON DELETE CASCADE
  - constraint: foreign key(item_id) references trend_items(id)
  - constraint: unique(snapshot_id, rank)
  - constraint: unique(snapshot_id, item_id)
- `api_requests.json` — API 调用审计与用量统计（每个工具一次调用一行），用于限流、排障与计费/配额（若部署为公共服务）。 (34 rows; fields: ['id', 'api_key_id', 'tool_name', 'source_id', 'request_params', 'cache_key', 'snapshot_id', 'response_status', 'latency_ms', 'served_from_cache', 'created_at', 'updated_at'])
  - constraint: response_status >= 100 AND response_status <= 599
  - constraint: latency_ms >= 0 AND latency_ms <= 300000

## Business rules enforced by the tools

- 每个对外工具名必须能映射到一个 sources.slug（固定来源）以及一个 sources.supports_params 校验器；若入参包含未声明字段或枚举值非法，则拒绝请求。
- get-bbc-news: 当 category 为空字符串时允许 edition 为 '', 'uk','us','int'；当 category 非空时 edition 必须为空字符串（与工具描述一致）。
- get-douban-rank: start 必须 >= 0；count 必须在 1..50；分页通过 snapshot_items.rank 排序后 OFFSET start LIMIT count 实现。
- get-ifanr-news: limit 必须在 1..50；offset 必须 >= 0；通过 snapshot_items.rank 做 OFFSET/LIMIT 或通过 extra 内的游标字段实现，但对外语义必须与 limit/offset 对齐。
- get-sspai-rank: limit 必须在 1..100；tag 必须为枚举值之一（热门文章/应用推荐/生活方式/效率技巧/少数派播客）。
- get-zhihu-trending: limit 必须在 1..100；若上游返回不足则按实际条目数返回，trend_snapshots.item_count 与 snapshot_items 行数必须一致。
- 对任一 tool_name + 规范化参数生成的 cache_key：若存在 status=ready 且 expires_at > now() 的 trend_snapshots，则读请求必须优先返回该快照（served_from_cache=true），且不得创建新的 running fetch_jobs（允许后台异步刷新除外）。
- 同一 cache_key 在任一时刻最多允许一个 fetch_jobs 处于 queued/running，防止并发击穿；并发读请求应复用同一 in-flight job 或回退到最近 stale 快照。
- fetch_jobs.status 只能按定义的状态机迁移；当变为 succeeded 时必须创建一条 trend_snapshots(status=ready) 并写入对应 snapshot_items；当 failed/cancelled 时不得创建 ready 快照。
- trend_items 通过 (source_id, canonical_key) 全局去重；相同 canonical_key 的条目只允许更新字段，不允许创建重复行。
- snapshot_items.rank 必须从1开始且在同一 snapshot 内唯一；snapshot_items(snapshot_id,item_id) 必须唯一，避免同一条目在同一快照重复出现。
- api_requests 每次工具调用必须落库一条记录；若命中快照则记录 snapshot_id 与 cache_key；若未命中且触发抓取则可在返回后补写 snapshot_id（更新 updated_at）。