# MiniMax — local MCP environment

This backend stores MiniMax multimodal generation activity (text-to-audio, voice cloning, text-to-image, and video generation), along with playable media artifacts produced by those requests. The main workflows are: submit a generation request (tracked with status and cost), persist resulting media files/URLs, and optionally list available voices and clone new voices that can later be used for TTS.

Repository: https://github.com/ropon/MiniMax-MCP
Homepage: https://smithery.ai/server/@ropon/minimax-mcp

## Datastore

- `api_credentials.json` — Per-tenant MiniMax API connection settings (host, keys) and quota controls used by all tools that call MiniMax. (12 rows; fields: ['id', 'tenant_id', 'api_host', 'api_key', 'status', 'monthly_request_quota', 'monthly_cost_usd_limit', 'current_month_requests', 'current_month_cost_usd_estimate', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'rotating']
  - constraint: unique(tenant_id, api_host)
  - constraint: monthly_request_quota >= 0
  - constraint: monthly_cost_usd_limit >= 0
  - constraint: current_month_requests >= 0
- `voices.json` — Catalog of voices available to a tenant, including system voices returned by list_voices and tenant-created cloned voices. (31 rows; fields: ['id', 'credential_id', 'external_minimax_voice_id', 'display_name', 'voice_type', 'origin', 'language', 'gender', 'status', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'creating', 'failed', 'disabled']
  - constraint: unique(credential_id, external_minimax_voice_id)
  - constraint: voice_type in ('system','voice_cloning')
  - constraint: origin in ('vendor_system','tenant_cloned')
  - constraint: status in ('available','creating','failed','disabled')
- `generation_requests.json` — All user-initiated generation calls (TTS, voice clone, text-to-image, and video). Stores tool parameters, vendor request ids, status, and cost estimates for quota enforcement. (41 rows; fields: ['id', 'credential_id', 'tool_name', 'status', 'vendor_request_id', 'model', 'prompt', 'aspect_ratio', 'voice_id', 'input_file', 'input_is_url', 'text', 'is_user_provided_content', 'request_payload', 'response_payload', 'error_message', 'cost_usd_estimate', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: tool_name in ('text_to_audio','voice_clone','text_to_image','generate_video')
  - constraint: cost_usd_estimate >= 0
  - constraint: input_is_url in (true,false)
  - constraint: is_user_provided_content in (true,false)
- `media_assets.json` — Materialized outputs (audio/image/video) and inputs (e.g., uploaded audio) referenced by requests and playable via play_audio. Stores local paths and/or remote URLs with type and format constraints. (34 rows; fields: ['id', 'credential_id', 'request_id', 'role', 'media_type', 'format', 'storage', 'local_path', 'remote_url', 'byte_size', 'duration_ms', 'sha256', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'deleted', 'expired']
  - constraint: byte_size >= 0 OR byte_size is null
  - constraint: duration_ms >= 0 OR duration_ms is null
  - constraint: ((storage='local') implies (local_path is not null AND remote_url is null))
  - constraint: ((storage='remote_url') implies (remote_url is not null AND local_path is null))
- `voice_catalog_snapshots.json` — Audit snapshots of list_voices responses per credential/voice_type filter, enabling debugging and historical comparisons even though the tool returns text. (27 rows; fields: ['id', 'credential_id', 'voice_type', 'raw_response', 'normalized_voice_ids', 'created_at', 'updated_at'])
  - lifecycle `voice_type`: ['all', 'system', 'voice_cloning']
  - constraint: voice_type in ('all','system','voice_cloning')
  - constraint: normalized_voice_ids is array

## Business rules enforced by the tools

- All mutating upstream tools (text_to_audio, voice_clone, text_to_image, generate_video) must create a generation_requests row with status='queued' before calling MiniMax, then transition to 'running' when the call is initiated, and finally to 'succeeded' or 'failed' with finished_at set.
- API calls must be rejected when api_credentials.status != 'active'.
- Before executing any COST WARNING tool, the service must enforce quotas: current_month_requests + 1 <= monthly_request_quota AND current_month_cost_usd_estimate + cost_usd_estimate <= monthly_cost_usd_limit; on success or failure, current_month_requests is incremented and cost estimate is added (or reconciled if actual cost is known).
- list_voices is only supported when api_credentials.api_host == 'https://api.minimax.chat'; otherwise the call must fail without creating/altering voices (but may log a snapshot with an error in raw_response if desired).
- list_voices must upsert voices by (credential_id, external_minimax_voice_id), setting voice_type/origin/metadata from the vendor response and status='available' for returned voices.
- voice_clone must require voice_id and input_file; it must create or update a voices row with origin='tenant_cloned' and status transitioning creating -> available/failed based on the upstream result.
- text_to_image must require prompt and only allow model='image-01' (default if omitted); aspect_ratio must be one of the enumerated ratios when provided.
- generate_video must allow only models in ['T2V-01','T2V-01-Director','I2V-01','I2V-01-Director','I2V-01-live'] when provided; requests should be marked failed if neither prompt nor an image input is present in request_payload.
- On successful generation, the service must create one or more media_assets rows with role='output' and media_type/format matching the produced artifact; request_id must reference the originating generation_requests row.
- play_audio must only operate on media_assets where media_type='audio', format in ('wav','mp3'), status='available', and either local_path matches the requested input_file_path (for local playback) or remote_url matches when is_url=true.