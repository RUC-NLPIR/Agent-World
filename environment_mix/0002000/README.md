# Pollinations Server — local MCP environment

该后端存储 Pollinations Server 的生成请求与产物（图像/文本），并提供下载追踪与配额控制。主要工作流包括：创建生成任务（记录prompt、模型、seed、隐私/安全等参数）→ 异步/同步生成并落库产物与URL/内容 →（可选）对生成的图像进行下载并记录下载事件与本地保存路径。

Repository: https://github.com/bendusy/pollinations-mcp
Homepage: https://smithery.ai/server/@bendusy/pollinations-mcp

## Datastore

- `api_clients.json` — 调用方/客户端身份与配额载体。用于把每次 generate_image/generate_text/download_image 的行为归属到一个客户端，并执行速率与用量限制。 (19 rows; fields: ['id', 'name', 'api_key_hash', 'status', 'daily_request_limit', 'daily_image_limit', 'daily_text_limit', 'daily_download_limit', 'created_at', 'updated_at', 'last_seen_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(api_key_hash)
  - constraint: daily_request_limit >= 0
  - constraint: daily_image_limit >= 0
  - constraint: daily_text_limit >= 0
- `generation_requests.json` — 统一记录 generate_image 与 generate_text 的请求参数、状态与生成结果指针。每条记录代表一次生成调用。 (18 rows; fields: ['id', 'client_id', 'kind', 'status', 'prompt', 'model', 'seed', 'private', 'response_json', 'system_prompt', 'image_width', 'image_height', 'image_nologo', 'image_enhance', 'image_safe', 'provider_request', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(client_id) references api_clients(id) on delete restrict
  - constraint: kind in ('image','text')
  - constraint: prompt length >= 1
  - constraint: model length >= 1
- `image_assets.json` — 图像生成成功后的产物元数据与可访问URL。用于支撑 generate_image 返回的URL，以及 download_image 的url来源校验与追踪。 (18 rows; fields: ['id', 'generation_id', 'status', 'provider_url', 'content_type', 'byte_size', 'sha256', 'width', 'height', 'is_private', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'deleted']
  - constraint: fk(generation_id) references generation_requests(id) on delete cascade
  - constraint: unique(generation_id)
  - constraint: provider_url like 'http%'
  - constraint: width between 64 and 4096
- `text_outputs.json` — 文本生成成功后的产物。用于支撑 generate_text 返回文本/JSON，并根据private标记控制访问。 (18 rows; fields: ['id', 'generation_id', 'status', 'format', 'content_text', 'content_json', 'is_private', 'token_count_estimate', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'deleted']
  - constraint: fk(generation_id) references generation_requests(id) on delete cascade
  - constraint: unique(generation_id)
  - constraint: format in ('plain','json')
  - constraint: ((format='plain' and content_text is not null and content_json is null) or (format='json' and content_json is not null))
- `download_events.json` — download_image 的下载审计与结果记录。保存输入url、输出路径、执行状态与错误信息。 (19 rows; fields: ['id', 'client_id', 'image_id', 'status', 'url', 'output_path', 'http_status', 'byte_size', 'sha256', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'downloading', 'succeeded', 'failed']
  - constraint: fk(client_id) references api_clients(id) on delete restrict
  - constraint: fk(image_id) references image_assets(id) on delete set null
  - constraint: url like 'http%'
  - constraint: length(output_path) >= 1

## Business rules enforced by the tools

- generate_image：必须创建一条 generation_requests(kind='image') 记录；prompt 必填；未提供 width/height/model/nologo/enhance/safe/private 时分别使用默认值 1024/1024/'flux'/true/false/false/false，并写入 generation_requests 对应字段。
- generate_text：必须创建一条 generation_requests(kind='text') 记录；prompt 必填；未提供 model/json/private 时分别使用默认值 'openai'/false/false；system 与 seed 若提供则落库。
- generation_requests.kind='image' 时：response_json 与 system_prompt 必须为NULL；image_* 字段必须非NULL（除seed允许NULL）。kind='text' 时：image_* 字段必须为NULL。
- 任一客户端状态非 active（suspended/revoked）时，拒绝执行三类工具并不产生新记录，或仅产生失败审计记录（实现二选一，但需一致）。
- 配额：每个 api_clients 在自然日内的请求数不得超过 daily_request_limit；图像生成次数不得超过 daily_image_limit；文本生成次数不得超过 daily_text_limit；下载次数不得超过 daily_download_limit。超限请求必须失败并在 generation_requests / download_events 中标记 failed 与错误码 'quota_exceeded'。
- 生成成功：kind='image' 的 generation_requests.status= 'succeeded' 时必须存在且仅存在一条 image_assets 记录（unique(generation_id)）；kind='text' 成功时必须存在且仅存在一条 text_outputs 记录。
- 隐私：generation_requests.private=true 时，关联的 image_assets/text_outputs.is_private 必须为 true；对外返回/列举时不得暴露私有资源给非同一 client_id（如实现有鉴权层）。
- download_image：必须创建 download_events 记录；url 必填；output_path 未提供时使用默认 'image.jpg'。若 url 匹配到 image_assets.provider_url，则写入 image_id 以便追踪；若匹配到 is_private=true 且 client_id 不一致，则必须拒绝下载并标记 failed（error_code='forbidden'）。
- 状态机：generation_requests 仅允许按 transitions 前进；一旦进入 succeeded/failed/cancelled 不得再变更。download_events 一旦 succeeded/failed 不得再变更。
- 输入范围：image_width/image_height 必须在 [64,4096]；seed 若提供必须在 [0,4294967295]；违反范围的请求必须失败并给出错误码 'invalid_argument'。