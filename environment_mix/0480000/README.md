# AI咖提示词管理MCP — local MCP environment

该后端用于管理用户提示词（Prompt）资产：用户通过令牌认证后，可按类型/分类列出提示词、按关键词搜索、查看某个提示词详情，并将带参数的提示词渲染为可直接使用的最终文本。系统同时记录提示词被使用的审计日志与用量统计，便于追踪与限流。

Repository: https://github.com/vines90/mcp-prompt-server
Homepage: https://smithery.ai/server/@vines90/mcp-prompt-server

## Datastore

- `users.json` — 用户账户与认证标识。authenticate_user 根据 user_token（用户ID或JWT）解析并映射到此表，后续所有提示词操作均以当前用户为作用域。 (18 rows; fields: ['id', 'display_name', 'email', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(email) where email is not null
  - constraint: display_name length between 1 and 80
  - constraint: status in ('active','suspended','deleted')
- `auth_tokens.json` — 用户身份令牌索引。支持 user_token 既可能是用户ID，也可能是JWT/不透明token：若为不透明token则在此表查找；若为用户ID则直接命中 users.id。用于 authenticate_user。 (18 rows; fields: ['id', 'user_id', 'token_hash', 'token_type', 'status', 'last_used_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'expired']
  - constraint: unique(token_hash)
  - constraint: user_id must reference users.id
  - constraint: expires_at is null or expires_at >= created_at
- `prompts.json` — 提示词主表。支持个人提示词与公共提示词的统一存储；list_user_prompts/search_user_prompts/use_user_prompt/get_user_prompt_info 均围绕此表查询与渲染。 (18 rows; fields: ['id', 'owner_user_id', 'name', 'visibility', 'category', 'description', 'template', 'param_schema', 'search_text', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(owner_user_id, name)
  - constraint: name length between 1 and 120
  - constraint: template length between 1 and 20000
  - constraint: visibility in ('private','public')
- `prompt_shares.json` — 提示词共享/授权表，用于 list_user_prompts(type=all) 与权限判定：除 owned(自己拥有) 与 public(公开) 外，用户还可通过此表获得他人私有提示词的访问权（真实系统常见）。虽然工具面未显式提供分享管理，但读取/使用时需要此层权限数据。 (18 rows; fields: ['id', 'prompt_id', 'shared_with_user_id', 'permission', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(prompt_id, shared_with_user_id)
  - constraint: permission in ('read','use')
  - constraint: prompt_id must reference prompts.id
  - constraint: shared_with_user_id must reference users.id
- `prompt_use_events.json` — 提示词使用与审计日志。use_user_prompt 每次渲染/使用都会写入一条事件，便于统计、排障与限流。 (20 rows; fields: ['id', 'user_id', 'prompt_id', 'prompt_name_snapshot', 'params', 'rendered_text', 'render_status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `render_status`: ['succeeded', 'failed']
  - constraint: user_id must reference users.id
  - constraint: prompt_id must reference prompts.id
  - constraint: render_status in ('succeeded','failed')
  - constraint: if render_status = 'failed' then error_message is not null

## Business rules enforced by the tools

- authenticate_user(user_token) MUST accept either a users.id (prefix aik_usr_) or a raw token; if raw token, the system MUST hash it and look up auth_tokens.token_hash where status='active' and (expires_at is null or expires_at > now()).
- If a user is in status='suspended' or 'deleted', authenticate_user MUST fail and no other tool may proceed.
- list_user_prompts(type='owned') MUST return prompts where owner_user_id = current_user.id AND status='active'.
- list_user_prompts(type='public') MUST return prompts where visibility='public' AND status='active'.
- list_user_prompts(type='all') MUST return the union of: owned(active) + public(active) + prompts shared to the user via prompt_shares(status='active') (and prompts.status='active').
- list_user_prompts(category=...) MUST filter by prompts.category exact match (or normalized match) in addition to type logic.
- list_user_prompts(limit) MUST default to 50 when omitted, MUST be clamped to an integer range [1, 200].
- search_user_prompts(query) MUST search only within the same visibility scope as list_user_prompts(type='all') (owned+public+shared) and MUST filter out prompts where status!='active'.
- search_user_prompts(query) MUST require query length >= 1 and SHOULD enforce an upper bound (e.g., 256 chars) to protect indexes.
- get_user_prompt_info(name) MUST resolve name within the current user's accessible scope: (owner_user_id=current_user.id) OR (visibility='public') OR (shared via prompt_shares active). If multiple prompts could match by name across scopes, resolution MUST prefer owned over shared over public, and ties MUST be deterministic.
- use_user_prompt(name, params) MUST use the same resolution rules as get_user_prompt_info(name) and MUST reject prompts where status!='active'.
- use_user_prompt(params) MUST only accept string values (as per tool schema); non-string values MUST be rejected or coerced to string before persistence.
- Prompt template rendering MUST replace {{key}} placeholders using params; if param_schema marks a key required and it is missing, render_status MUST be 'failed' and an event MUST be written to prompt_use_events with error_message populated.
- Every call to use_user_prompt MUST insert a prompt_use_events row recording user_id, prompt_id, params, rendered_text (or an allowed summary), render_status, and timestamps.
- A user MUST NOT be able to use a private prompt they do not own unless a prompt_shares record exists with status='active' and permission in ('use') (read-only shares may allow get_user_prompt_info but must not allow use_user_prompt).
- FK integrity MUST be enforced: deleting a user is a soft-delete (users.status='deleted'); prompts/prompt_shares/auth_tokens remain for audit but must be excluded from active operations.
- When prompts.name/description/template changes, prompts.search_text MUST be recalculated and updated within the same transaction.