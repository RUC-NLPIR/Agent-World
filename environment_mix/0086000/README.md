# 高德地图 MCP Server — local MCP environment

该后端用于支撑“高德地图 MCP Server”的多种查询类工具：地理编码/逆地理编码、IP 定位、天气、POI 搜索/详情、距离测算与多种出行路径规划。系统核心工作流是：客户端携带某个 MCP 会话与鉴权上下文发起工具调用，服务对参数进行规范化与缓存命中判断，必要时向高德开放平台转发请求并持久化请求/响应与配额消耗，用于审计、限流、计费与问题追踪。

Repository: https://github.com/sseaan/amap-mcp-server
Homepage: https://smithery.ai/server/@sseaan/amap-mcp-server

## Datastore

- `tenants.json` — 租户/工作空间维度的数据隔离与配额管理单元。一个 tenant 可绑定一个或多个高德开放平台 Key（用于轮询/容灾/多环境）。 (31 rows; fields: ['id', 'name', 'status', 'default_region', 'daily_request_quota', 'monthly_request_quota', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: daily_request_quota >= 0
  - constraint: monthly_request_quota >= 0
- `api_keys.json` — MCP Server 自身的调用鉴权 Key（给客户端用）以及关联到某个 tenant。用于按 key 计量、限流、撤销与审计。 (30 rows; fields: ['id', 'tenant_id', 'key_prefix', 'key_hash', 'status', 'last_used_at', 'requests_per_minute_limit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: requests_per_minute_limit >= 0
  - constraint: fk(tenant_id) references tenants(id) on delete restrict
- `amap_provider_keys.json` — 高德开放平台的 provider key 配置（真正对外请求高德API所需）。同一 tenant 可配置多个用于轮询/灰度/容灾，并可按状态禁用。 (31 rows; fields: ['id', 'tenant_id', 'label', 'provider_key_ciphertext', 'status', 'weight', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(tenant_id, label)
  - constraint: weight >= 0
  - constraint: fk(tenant_id) references tenants(id) on delete cascade
- `tool_calls.json` — 所有 MCP 工具调用的请求/响应日志与状态机。覆盖本服务的 16 个 tools：regeocode/geo/ip_location/weather、骑行/步行/驾车/公交路径规划（地址或坐标）、distance、text_search/around_search/search_detail。 (38 rows; fields: ['id', 'tenant_id', 'api_key_id', 'provider_key_id', 'mcp_session_id', 'tool_name', 'status', 'request_params', 'normalized_params', 'cache_key', 'cache_ttl_seconds', 'http_status', 'provider_endpoint', 'provider_request_id', 'response_body', 'error_code', 'error_message', 'duration_ms', 'billed_units', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'validated', 'cache_hit', 'dispatched', 'succeeded', 'failed', 'rate_limited']
  - constraint: fk(tenant_id) references tenants(id) on delete cascade
  - constraint: fk(api_key_id) references api_keys(id) on delete set null
  - constraint: fk(provider_key_id) references amap_provider_keys(id) on delete set null
  - constraint: cache_ttl_seconds is null or (cache_ttl_seconds >= 0 and cache_ttl_seconds <= 604800)
- `usage_rollups.json` — 按时间窗口聚合的用量表，用于快速限流/配额校验与账单统计。写入策略通常为按分钟/小时增量 upsert。 (36 rows; fields: ['id', 'tenant_id', 'api_key_id', 'tool_name', 'window_start', 'window_granularity', 'requests_count', 'success_count', 'error_count', 'rate_limited_count', 'billed_units', 'created_at', 'updated_at'])
  - lifecycle `window_granularity`: ['minute', 'hour', 'day', 'month']
  - constraint: fk(tenant_id) references tenants(id) on delete cascade
  - constraint: fk(api_key_id) references api_keys(id) on delete cascade
  - constraint: unique(tenant_id, api_key_id, tool_name, window_granularity, window_start)
  - constraint: requests_count >= 0

## Business rules enforced by the tools

- 所有 tool_calls 必须关联 tenant_id；若提供 api_key，则 api_keys.status 必须为 active 且 api_keys.tenant_id 必须等于 tool_calls.tenant_id，否则拒绝并记录 status=rate_limited 或 failed(鉴权失败)。
- tenant.status=suspended 或 deleted 时，禁止创建新的 tool_calls（直接 rate_limited/failed），但允许读取历史记录（如果服务提供管理端）。
- 创建 tool_calls 后，状态只能按照 tool_calls.lifecycle.transitions 发生变化；任何越级状态更新必须被拒绝并报警。
- 缓存规则：当 tool_calls.normalized_params 生成成功时必须生成 cache_key；若命中缓存则 status 必须从 validated -> cache_hit -> succeeded 且 provider_key_id/provider_endpoint 可以为空。
- 若未命中缓存并需要请求高德，则必须选择 status=active 的 amap_provider_keys；选择逻辑按 weight 加权轮询/最小失败率等策略实现，但写入的 provider_key_id 必须属于同一 tenant。
- 配额与限流：当同一 api_key_id 在当前分钟窗口内 usage_rollups.requests_count 达到 api_keys.requests_per_minute_limit 时，新请求必须标记为 rate_limited，并将 usage_rollups.rate_limited_count 递增。
- 租户配额：当 tenant 在当日/当月窗口内 requests_count 达到 tenants.daily_request_quota 或 tenants.monthly_request_quota 时，新的 tool_calls 必须 rate_limited。
- 计量：每个 tool_call 的 billed_units 默认=1；若发生重试（同一 tool_call 内部重试不额外计费）则 billed_units 不增加；若实现为拆分多次 provider 调用，则 billed_units 必须等于 provider 调用次数并同步到 usage_rollups。
- 数据完整性：tool_calls.response_body 仅在 status=succeeded 时允许非空；tool_calls.error_code/error_message 仅在 status=failed 或 rate_limited 时允许非空。
- 参数映射：由于工具参数 schema 为空，服务必须把工具调用传入的所有参数原样存入 tool_calls.request_params，并将解析得到的标准字段（如 origin/destination、location、keywords、city/adcode、ip、radius、extensions 等）放入 normalized_params 用于缓存与审计。