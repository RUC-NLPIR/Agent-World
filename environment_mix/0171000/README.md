# ElevenLabs MCP Server — local MCP environment

This backend models an ElevenLabs MCP gateway that brokers user-initiated audio/voice/agent operations to the ElevenLabs API (and Twilio for outbound calls), while persisting voice library metadata, conversational agent configs, knowledge base attachments, and an auditable log of costly generations/transcriptions/conversions. Main workflows: search/get/clone voices, generate TTS/SFX/STT/STS outputs, manage agents and their knowledge bases, and place outbound calls using an agent and a provisioned phone number.

Repository: https://github.com/elevenlabs/elevenlabs-mcp
Homepage: https://smithery.ai/server/@elevenlabs/elevenlabs-mcp

## Datastore

- `accounts.json` — Represents an ElevenLabs workspace/account the MCP server is configured to access, including subscription state snapshots and operational quotas enforced by the MCP gateway to prevent unexpected vendor cost. (12 rows; fields: ['id', 'display_name', 'vendor_workspace_id', 'status', 'default_output_dir', 'subscription_tier', 'subscription_status', 'subscription_renewal_at', 'vendor_usage_character_count', 'vendor_usage_character_limit', 'gateway_daily_cost_limit_usd', 'gateway_daily_cost_used_usd', 'gateway_daily_window_started_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'disabled']
  - constraint: unique(vendor_workspace_id)
  - constraint: gateway_daily_cost_limit_usd >= 0
  - constraint: gateway_daily_cost_used_usd >= 0
- `voices.json` — Cached metadata about voices accessible to the account: owned/library voices, shared voice library entries, and generated preview voices. Supports search/get and is referenced by TTS/agents/voice operations. (31 rows; fields: ['id', 'account_id', 'vendor_voice_id', 'scope', 'name', 'description', 'category', 'labels', 'created_at_unix', 'preview_generated_from_prompt', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(account_id, vendor_voice_id, scope)
  - constraint: created_at_unix is null or created_at_unix >= 0
- `agents.json` — Conversational AI agent configurations created/managed through ElevenLabs. References a voice and is used for outbound calling and knowledge base attachments. (35 rows; fields: ['id', 'account_id', 'vendor_agent_id', 'name', 'first_message', 'system_prompt', 'language_code', 'voice_id', 'vendor_voice_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(account_id, vendor_agent_id)
  - constraint: name <> ''
- `agent_knowledge_bases.json` — Knowledge base items attached to agents. Each entry is created by URL ingestion or file upload (epub/pdf/docx/txt/html) and tracked for processing status. (36 rows; fields: ['id', 'account_id', 'agent_id', 'vendor_agent_id', 'knowledge_base_name', 'source_type', 'url', 'input_file_path', 'file_mime_type', 'file_extension', 'vendor_knowledge_base_id', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'processing', 'ready', 'failed', 'removed']
  - constraint: source_type='url' implies url is not null and input_file_path is null
  - constraint: source_type='file' implies input_file_path is not null
  - constraint: file_extension is null or file_extension in ('epub','pdf','docx','txt','html')
  - constraint: unique(agent_id, knowledge_base_name)
- `operations.json` — Auditable log of all tool invocations that may call external services (ElevenLabs, Twilio) and/or produce files. Captures inputs/outputs, paths, estimated cost, and status for replay/debugging and quota enforcement. (41 rows; fields: ['id', 'account_id', 'tool_name', 'status', 'requested_at', 'started_at', 'finished_at', 'input', 'output', 'error_message', 'vendor_request_id', 'vendor_resource_id', 'voice_id', 'agent_id', 'knowledge_base_id', 'input_file_path', 'output_file_paths', 'output_text_path', 'audio_format', 'duration_seconds', 'language_code', 'search_query', 'sort', 'sort_direction', 'page', 'page_size', 'to_number_e164', 'agent_phone_number_id', 'estimated_cost_usd', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'canceled']
  - constraint: estimated_cost_usd >= 0
  - constraint: duration_seconds is null or (duration_seconds >= 0.5 and duration_seconds <= 5.0)
  - constraint: page is null or page >= 0
  - constraint: page_size is null or (page_size >= 1 and page_size <= 100)

## Business rules enforced by the tools

- All tools must create an operations row with status=queued, then transition to running, then succeeded/failed/canceled; finished_at must be set for terminal states.
- Costly tools (speech_to_text, text_to_sound_effects, voice_clone, isolate_audio, create_agent, add_knowledge_base_to_agent, speech_to_speech, text_to_voice, create_voice_from_preview, make_outbound_call, text_to_speech) must be blocked when accounts.gateway_daily_cost_used_usd + operations.estimated_cost_usd would exceed accounts.gateway_daily_cost_limit_usd.
- check_subscription updates accounts.subscription_tier/subscription_status/subscription_renewal_at and vendor usage snapshots; it must also write an operations record.
- search_voices must query voices where account_id matches and scope in ('user_library','generated_preview'); it must support filtering by search term across name/description/category and labels values; sorting must honor sort_direction and allow created_at_unix when present.
- search_voice_library must query voices where account_id matches and scope='shared_library'; it must enforce page>=0 and 1<=page_size<=100 and persist the query parameters in operations.search_query/page/page_size.
- get_voice must return a voice by vendor_voice_id or cached id; if not present in cache, the system may fetch from vendor and upsert voices with scope inferred, then mark last_synced_at.
- create_agent must create a row in agents with status=active, persist vendor_agent_id, and link voice_id when the voice exists in cache; otherwise vendor_voice_id must be stored.
- list_agents and get_agent must read from agents; if a vendor fetch occurs, it must reconcile/upsert by (account_id, vendor_agent_id).
- add_knowledge_base_to_agent must create agent_knowledge_bases with status=queued and transition through processing to ready/failed; it must enforce allowed file types (epub/pdf/docx/txt/html) when source_type='file'.
- text_to_sound_effects must enforce duration_seconds in [0.5, 5.0] and record the resulting output_file_paths in operations.
- text_to_voice must create one operations row capturing all three preview output files; it must upsert voices with scope='generated_preview' for the generated vendor_voice_id if returned.
- create_voice_from_preview must create or update a voices row with scope='user_library' for the resulting vendor_voice_id and mark any corresponding generated_preview voice as archived if vendor semantics indicate promotion.
- make_outbound_call must validate to_number_e164 format begins with '+' and contains digits only thereafter; it must record the vendor call identifier in operations.vendor_resource_id.
- play_audio must only accept audio_format in ('wav','mp3') and must reference an existing local file path in operations.input_file_path (checked by runtime) while still writing an operations record for auditing.