# MCPollinations Multimodal Server — local MCP environment

This backend powers a multimodal generation gateway that can create images (as URLs or base64), generate text responses, and produce text-to-speech audio. It stores model/voice catalogs, individual generation requests with their parameters and lifecycle, and the resulting artifacts (image/audio/text) with metadata for auditing, replay, and rate/quota enforcement.

Repository: https://github.com/pinkpixel-dev/MCPollinations
Homepage: https://smithery.ai/server/@pinkpixel-dev/mcpollinations

## Datastore

- `clients.json` — Represents an API consumer (user, integration, or local agent) and its quota/rate policy for multimodal generation. (27 rows; fields: ['id', 'display_name', 'status', 'api_key_hash', 'quota_daily_requests', 'quota_daily_images', 'quota_daily_text', 'quota_daily_audio', 'rate_limit_per_minute', 'notes', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(api_key_hash) where api_key_hash is not null
  - constraint: quota_daily_requests >= 0
  - constraint: quota_daily_images >= 0
  - constraint: quota_daily_text >= 0
- `model_catalog.json` — Catalog of available generation backends: image models, text models, and audio voices. Serves listImageModels/listTextModels/listAudioVoices and validation for generation requests. (31 rows; fields: ['id', 'modality', 'key', 'display_name', 'status', 'vendor', 'capabilities', 'sort_order', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: unique(modality, key)
  - constraint: sort_order >= 0
- `generation_requests.json` — Immutable record of a generation invocation for image/text/audio including all tool parameters and operational metadata. (38 rows; fields: ['id', 'client_id', 'tool_name', 'modality', 'prompt', 'seed', 'model_catalog_id', 'model_key', 'width', 'height', 'enhance', 'safe', 'output_path', 'file_name', 'format', 'status', 'error_code', 'error_message', 'remote_request_id', 'started_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: prompt length between 1 and 20000
  - constraint: seed is null or (seed >= 0 and seed <= 2147483647)
  - constraint: width is null or (width >= 64 and width <= 4096)
  - constraint: height is null or (height >= 64 and height <= 4096)
- `artifacts.json` — Generated outputs (image, audio, text) for a generation request, including URLs, base64 payloads, and file-save metadata. (39 rows; fields: ['id', 'generation_request_id', 'artifact_type', 'mime_type', 'url', 'base64_data', 'text_content', 'file_path', 'file_name', 'file_format', 'size_bytes', 'status', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'expired', 'deleted']
  - constraint: foreign key (generation_request_id) references generation_requests(id) on update restrict on delete cascade
  - constraint: size_bytes is null or size_bytes >= 0
  - constraint: if artifact_type = 'image_url' then url is not null
  - constraint: if artifact_type in ('image_base64','audio_base64') then base64_data is not null
- `usage_events.json` — Append-only metering events for quota/rate enforcement and auditing across all tools. (33 rows; fields: ['id', 'client_id', 'generation_request_id', 'tool_name', 'modality', 'request_units', 'success', 'http_status', 'latency_ms', 'created_at', 'updated_at'])
  - lifecycle `success`: ['true', 'false']
  - constraint: foreign key (client_id) references clients(id) on update restrict on delete set null
  - constraint: foreign key (generation_request_id) references generation_requests(id) on update restrict on delete set null
  - constraint: request_units between 0 and 100
  - constraint: http_status is null or (http_status between 100 and 599)

## Business rules enforced by the tools

- For generateImageUrl and generateImage, the resolved image model must correspond to an active or deprecated model_catalog entry where modality='image_model'; disabled models must be rejected.
- For respondText, the resolved text model must correspond to an active or deprecated model_catalog entry where modality='text_model'; disabled models must be rejected.
- For respondAudio, the resolved voice must correspond to an active or deprecated model_catalog entry where modality='audio_voice'; disabled voices must be rejected.
- If a tool omits model/voice, the backend must select the default based on modality: image='flux', text='openai', audio voice='alloy' (from model_catalog.key), and persist the resolved selection into generation_requests.model_catalog_id and generation_requests.model_key.
- If seed is omitted, the backend must generate a random integer seed in [0, 2147483647] and persist it on generation_requests.seed for reproducibility.
- Image dimensions default to width=1024 and height=1024 when omitted; requests must be rejected if width/height are outside [64, 4096] or if width*height exceeds a configured maximum pixel budget (e.g., 8,388,608).
- For generateImage, format defaults to 'png' and must be one of png/jpeg/jpg/webp; the saved artifact must include artifacts.file_path, artifacts.file_name, artifacts.file_format and artifacts.mime_type.
- For generateImageUrl, the server must create an artifacts row with artifact_type='image_url' and a non-null url; it must not store base64_data for that artifact.
- For respondText, the server must create an artifacts row with artifact_type='text' and non-null text_content.
- For respondAudio, the server must create an artifacts row with artifact_type in ('audio_file','audio_base64'); if played through the system, file_path should be populated when a temporary file is used.
- generation_requests.status must follow the declared transitions; once in succeeded/failed/cancelled it must be immutable except for updated_at and late-populated error_message/remote_request_id.
- Each tool invocation must append a usage_events row; generation tools must also link usage_events.generation_request_id to the created generation_requests row.
- If clients are enabled, requests must be rejected when the client is suspended/deleted or when daily quotas would be exceeded; quota checks must consider usage_events for the client's local day boundary.
- Rate limiting must enforce clients.rate_limit_per_minute by counting usage_events over a rolling 60-second window; catalog listing tools may be charged 0 or 1 units but must still be recorded.