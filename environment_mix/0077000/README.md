# Pulse CN MCP Server — local MCP environment

Pulse CN MCP Server 聚合多个中文互联网平台的实时热榜与轻量内容（星座运势、每日英文句子），并以工具形式对外提供查询。后端主要工作流是：记录每次工具调用（含参数、调用方）、按数据源抓取/拉取外部API响应并缓存成“快照”，再按请求参数（limit、星座type/time、random）从快照中读取并返回，同时进行基础的配额与可观测性统计。

Repository: https://github.com/wangtsiao/pulse-cn-mcp
Homepage: https://smithery.ai/server/@wangtsiao/pulse-cn-mcp

## Datastore

- `api_clients.json` — 调用本 MCP 服务的客户端/租户实体，用于鉴权、限流与计量。若部署为单租户，也可仅存一个默认客户端。 (12 rows; fields: ['id', 'name', 'status', 'default_timezone', 'rate_limit_rpm', 'daily_quota_requests', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: rate_limit_rpm >= 1 AND rate_limit_rpm <= 6000
  - constraint: daily_quota_requests = -1 OR daily_quota_requests >= 0
  - constraint: default_timezone <> ''
- `api_keys.json` — 客户端访问凭证。工具调用必须绑定到一个 api_key，用于审计、限流与配额扣减。 (20 rows; fields: ['id', 'client_id', 'key_prefix', 'key_hash', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(client_id, key_prefix)
  - constraint: key_prefix <> ''
  - constraint: FK(api_keys.client_id) REFERENCES api_clients(id) ON DELETE RESTRICT
- `data_sources.json` — 外部数据源定义（微博/知乎/抖音/百度等），包含拉取策略、缓存TTL与健康状态。所有热榜/内容工具都映射到某个 data_source（或一组 data_source）。 (20 rows; fields: ['id', 'code', 'display_name', 'category', 'status', 'fetch_method', 'endpoint_url', 'default_limit', 'max_limit', 'cache_ttl_seconds', 'last_success_at', 'last_error_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['enabled', 'disabled', 'degraded']
  - constraint: unique(code)
  - constraint: cache_ttl_seconds >= 5 AND cache_ttl_seconds <= 86400
  - constraint: default_limit IS NULL OR default_limit >= 1
  - constraint: max_limit IS NULL OR max_limit >= 1
- `fetch_snapshots.json` — 对外部数据源的一次拉取结果快照（缓存）。热点榜单、星座运势、每日句子均以快照形式落库，工具读取最新且未过期的快照；若缺失/过期则触发新拉取并写入新快照。 (34 rows; fields: ['id', 'source_id', 'cache_key', 'status', 'fetched_at', 'expires_at', 'http_status', 'error_message', 'raw_payload', 'normalized_items', 'items_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'failed']
  - constraint: FK(fetch_snapshots.source_id) REFERENCES data_sources(id) ON DELETE RESTRICT
  - constraint: unique(source_id, cache_key, fetched_at)
  - constraint: items_count >= 0
  - constraint: http_status IS NULL OR (http_status >= 100 AND http_status <= 599)
- `tool_invocations.json` — 每次 MCP 工具调用的审计与计量记录。将工具参数（limit、type、time、random）持久化，并关联到使用到的快照，便于回放、排障与统计。 (31 rows; fields: ['id', 'client_id', 'api_key_id', 'tool_name', 'request_params', 'limit', 'horoscope_type', 'horoscope_time', 'sentence_random', 'status', 'snapshot_ids', 'latency_ms', 'error_code', 'error_message', 'invoked_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'served_from_cache', 'fetched_live', 'failed', 'rate_limited']
  - constraint: FK(tool_invocations.client_id) REFERENCES api_clients(id) ON DELETE RESTRICT
  - constraint: FK(tool_invocations.api_key_id) REFERENCES api_keys(id) ON DELETE RESTRICT
  - constraint: latency_ms IS NULL OR latency_ms >= 0
  - constraint: limit IS NULL OR limit > 0

## Business rules enforced by the tools

- 所有工具调用必须携带可解析为某条 api_keys 记录的凭证，且 api_keys.status='active' 且 api_clients.status='active'；否则拒绝并记录 tool_invocations.status='failed' 或 'rate_limited'（视实现）。
- 每次工具调用必须写入一条 tool_invocations 记录，tool_name 必须为工具表面之一；request_params 必须与对应 JSON-Schema 相符，且 additionalProperties=false（未知字段拒绝）。
- limit 参数（出现在 internet-hotspots-aggregator、today-headlines-hotspots、the-paper-news-hotspots 等）必须严格大于 0；服务端实际使用值必须 clamp 到 data_sources.max_limit（若配置）并在响应中最多返回该数量。
- get-realtime-horoscope：horoscope_type 必须为12星座之一且 horoscope_time 必须为 today/nextday/week/month 之一；cache_key 必须包含 type 与 time（例如 horoscope|type=aries|time=today）。
- get-inspirational-english-sentence：sentence_random 必须为布尔值；cache_key 必须包含 random（例如 sentence|random=true）。当 random=true 时，可选择不复用缓存或使用更短 TTL（通过 data_sources.cache_ttl_seconds 配置）。
- 无参热榜工具（如 get-weibo-hotspots、zhihu-realtime-hotspots 等）使用各自 data_source.code 的默认 cache_key（例如 weibo_hotspots|default）。
- 读取流程：若存在 fetch_snapshots.status='fresh' 且 expires_at>now() 的最新快照（按 source_id+cache_key），工具应优先 served_from_cache；否则触发外部拉取并写入新 fetch_snapshots（成功则 status='fresh'，失败则 status='failed'），并将调用标记为 fetched_live 或 failed。
- internet-hotspots-aggregator 必须对其包含的多个 data_sources 分别取数并在 tool_invocations.snapshot_ids 记录所有使用的快照ID；对单个源失败时可降级返回部分结果，但必须将 data_sources.status 置为 degraded（可选异步）并在 tool_invocations.request_params/错误字段中记录降级信息。
- 当外部拉取失败：fetch_snapshots.status='failed' 必须写入 error_message；若存在未过期但较旧的快照，可允许“stale-while-revalidate”策略：返回旧快照并将其标记为 stale，同时记录 tool_invocations.status='served_from_cache' 且附加告警信息（实现可选，但状态转换必须符合 lifecycle）。
- 配额规则：同一 api_client 的请求在自然日累计不得超过 daily_quota_requests（-1 除外）；超过则拒绝并记录 tool_invocations.status='rate_limited'。限流规则：每分钟请求数不得超过 rate_limit_rpm（滑动窗口/令牌桶实现均可）。
- FK 完整性：删除 api_clients 必须先撤销/迁移其 api_keys 与相关 tool_invocations；删除 data_sources 必须先清理对应 fetch_snapshots（或禁止删除，仅 disabled）。
- 数据源配置变更（cache_ttl_seconds/max_limit/default_limit）只影响之后生成的 fetch_snapshots.expires_at 与工具输出裁剪，不回写历史快照。