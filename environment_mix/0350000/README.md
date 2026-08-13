# Gemini Server — local MCP environment

This backend powers an MCP "Gemini Server" that proxies Google Gemini (AI Studio) generation, chat sessions, function-call mediation, and manages Gemini File API uploads and Cached Content resources. It stores stateful chat sessions/messages, tracks generation requests (streaming and non-streaming), and mirrors remote Gemini resource metadata (files/caches) so list/get/delete/update operations can be served consistently and audited.

Repository: https://github.com/bsmi021/mcp-gemini-server
Homepage: https://smithery.ai/server/@bsmi021/mcp-gemini-server

## Datastore

- `api_keys.json` — Represents a configured upstream credential used to call Google Gemini (AI Studio) or Vertex AI. Used for quota enforcement, feature gating (files API not supported on Vertex), and auditing which credential was used for each request. (12 rows; fields: ['id', 'provider', 'display_name', 'key_hash', 'key_last4', 'project', 'location', 'status', 'daily_request_limit', 'daily_token_limit', 'requests_today', 'tokens_today', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(provider, key_hash)
  - constraint: daily_request_limit >= 0
  - constraint: daily_token_limit >= 0
  - constraint: requests_today >= 0
- `generation_requests.json` — Immutable-ish log of model generation calls (generateContent, generateContentStream, functionCall) including inputs, model configuration, safety settings, and outputs/usage. Streaming requests may have partial outputs captured as they arrive. (20 rows; fields: ['id', 'api_key_id', 'tool_name', 'model', 'is_stream', 'chat_session_id', 'prompt_text', 'contents', 'generation_config', 'safety_settings', 'tools_declarations', 'function_call_request', 'response_text', 'response_raw', 'usage', 'status', 'error_code', 'error_message', 'started_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: is_stream = true implies tool_name in ('gemini_generateContentStream')
  - constraint: is_stream = false implies tool_name in ('gemini_generateContent','gemini_functionCall','gemini_sendMessage','gemini_sendFunctionResult')
  - constraint: completed_at is null or started_at is not null
  - constraint: status in ('succeeded','failed','cancelled') implies completed_at is not null
- `chat_sessions.json` — Stateful chat sessions created via gemini_startChat. Stores session-wide model/config and links to messages exchanged in that session. (18 rows; fields: ['id', 'api_key_id', 'model', 'generation_config', 'safety_settings', 'system_instruction', 'status', 'ended_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'ended', 'archived']
  - constraint: status = 'ended' implies ended_at is not null
- `chat_messages.json` — Messages within a chat session including user prompts, model responses, and function call requests/results. Each sendMessage/sendFunctionResult produces one or more message records and links to the underlying generation request for audit. (19 rows; fields: ['id', 'chat_session_id', 'generation_request_id', 'sequence', 'role', 'content', 'text', 'function_call', 'function_result', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['committed', 'deleted']
  - constraint: unique(chat_session_id, sequence)
  - constraint: sequence >= 1
  - constraint: role = 'tool' implies function_result is not null
  - constraint: role = 'model' and function_call is not null implies function_result is null
- `uploaded_files.json` — Mirrors metadata for Gemini File API uploads. Used by upload/list/get/delete tools. Stores local upload source path for auditing and the upstream returned file name/uri. (18 rows; fields: ['id', 'api_key_id', 'upstream_name', 'uri', 'display_name', 'mime_type', 'size_bytes', 'local_path', 'sha256', 'upstream_state', 'status', 'uploaded_at', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'deleting', 'deleted', 'error']
  - constraint: unique(api_key_id, upstream_name)
  - constraint: size_bytes is null or size_bytes >= 0
  - constraint: status = 'deleted' implies deleted_at is not null
- `cached_contents.json` — Mirrors Gemini Cached Content resources used to reduce latency/cost for reused prompts. Used by create/list/get/update/delete cache tools and enforces TTL/displayName updates. (18 rows; fields: ['id', 'api_key_id', 'upstream_name', 'model', 'display_name', 'contents', 'ttl_seconds', 'expire_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'deleting', 'deleted', 'error']
  - constraint: unique(api_key_id, upstream_name)
  - constraint: ttl_seconds >= 60
  - constraint: ttl_seconds <= 2592000
  - constraint: status in ('expired','deleted') implies expire_at is not null or status = 'deleted'

## Business rules enforced by the tools

- exampleTool performs no data mutation and may return static help text; no collection changes are required.
- Any call that invokes Gemini (generateContent, generateContentStream, functionCall, sendMessage, sendFunctionResult) MUST create a generation_requests row in status='queued' then transition through running to a terminal state (succeeded|failed|cancelled).
- A generation_requests row MUST reference an api_keys row with status='active'; otherwise the request must fail with error_code='key_disabled'.
- For provider='vertex_ai', tools gemini_uploadFile/gemini_listFiles/gemini_getFile/gemini_deleteFile MUST be rejected; for provider='google_ai_studio' they are allowed.
- gemini_startChat MUST create a chat_sessions row with status='active'. Any provided initial history must be persisted as chat_messages with sequential ordering starting at 1.
- gemini_sendMessage MUST require an existing chat_sessions row in status='active'; it MUST append a user chat_messages record and then append a model chat_messages record (text and/or function_call).
- gemini_sendFunctionResult MUST require an existing chat_sessions row in status='active' and at least one prior model message with function_call not yet followed by a tool message; it MUST append a tool message with function_result then append the model's subsequent response.
- chat_messages.sequence MUST be strictly increasing per chat_session_id; inserts must use a transaction or per-session sequence allocator to maintain uniqueness.
- gemini_uploadFile MUST create an uploaded_files row; on success set upstream_name, uri, status='available', uploaded_at not null; on upstream failure set status='error' and store error information in an associated generation_requests row or application logs.
- gemini_deleteFile MUST transition uploaded_files.status to 'deleting' then 'deleted' and set deleted_at. Repeated deletes on already-deleted resources must be idempotent and keep status='deleted'.
- gemini_createCache MUST create a cached_contents row with status='active' and ttl_seconds within [60, 2592000]; expire_at must be computed as created_at + ttl_seconds.
- gemini_updateCache may only update cached_contents.display_name and/or ttl_seconds; updating ttl_seconds MUST recompute expire_at and is only allowed while status='active' (or must fail with error_code='cache_not_active').
- gemini_deleteCache MUST transition cached_contents.status to 'deleting' then 'deleted'. Deleting an already-deleted cache must be idempotent.
- Listing tools (gemini_listFiles, gemini_listCaches) MUST support pagination by filtering on created_at and id as a stable cursor and return a next_page_token derived from (created_at, id).
- Quota enforcement: before starting any generation_requests call, api_keys.requests_today+1 must not exceed daily_request_limit and projected tokens_today must not exceed daily_token_limit; otherwise the request must fail with error_code='quota_exceeded'.