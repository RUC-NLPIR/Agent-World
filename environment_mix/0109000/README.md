# Vapi MCP Server — local MCP environment

This backend stores configuration for voice AI assistants, the phone numbers attached to an account, and the lifecycle of outbound calls placed through those assistants. It also catalogs callable “tools” that assistants can invoke, and tracks which tools are enabled per assistant so the API can list and fetch assistants, calls, phone numbers, and tools.

Repository: https://github.com/VapiAI/mcp-server
Homepage: https://smithery.ai/server/@VapiAI/vapi-mcp-server

## Datastore

- `assistants.json` — Voice assistant configurations created by a customer. Assistants can be attached to outbound calls and granted access to a set of tools. (19 rows; fields: ['assistant_id', 'display_name', 'description', 'voice_config', 'model_config', 'webhook_url', 'status', 'version', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'active', 'disabled', 'archived']
  - constraint: unique(display_name)
  - constraint: version >= 1
  - constraint: status in ('draft','active','disabled','archived')
  - constraint: webhook_url is null OR webhook_url like 'https://%'
- `phone_numbers.json` — Inbound/outbound capable phone numbers owned/managed by the customer, used as caller IDs or routing endpoints for calls. (17 rows; fields: ['phone_number_id', 'e164', 'country_code', 'capabilities', 'provider', 'provider_ref', 'friendly_name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['provisioning', 'active', 'suspended', 'released']
  - constraint: unique(e164)
  - constraint: e164 like '+%'
  - constraint: status in ('provisioning','active','suspended','released')
  - constraint: provider is null OR provider in ('twilio','vonage','telnyx','other')
- `calls.json` — Outbound call records created via the API. Tracks destination, caller ID, assistant used, and lifecycle state for get/list operations. (19 rows; fields: ['call_id', 'assistant_id', 'from_phone_number_id', 'from_e164_override', 'to_e164', 'direction', 'status', 'started_at', 'ended_at', 'duration_seconds', 'error_code', 'error_message', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'dialing', 'in_progress', 'completed', 'failed', 'canceled']
  - constraint: to_e164 like '+%'
  - constraint: from_e164_override is null OR from_e164_override like '+%'
  - constraint: NOT (from_phone_number_id is not null AND from_e164_override is not null)
  - constraint: direction = 'outbound'
- `tools.json` — Catalog of tools that can be listed/fetched and optionally enabled for assistants. Represents vendor-provided and user-configured tools. (18 rows; fields: ['tool_id', 'slug', 'display_name', 'description', 'schema', 'integration_type', 'endpoint_url', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: unique(slug)
  - constraint: integration_type in ('builtin','webhook','mcp')
  - constraint: endpoint_url is null OR endpoint_url like 'https://%'
- `assistant_tools.json` — Join table defining which tools are enabled for which assistants, with per-assistant overrides. (18 rows; fields: ['assistant_tool_id', 'assistant_id', 'tool_id', 'enabled', 'config_override', 'created_at', 'updated_at'])
  - constraint: unique(assistant_id, tool_id)
  - constraint: enabled in (true,false)
  - constraint: FK assistant_id references assistants.assistant_id on delete cascade
  - constraint: FK tool_id references tools.tool_id on delete restrict

## Business rules enforced by the tools

- list_assistants returns assistants where status != 'archived', ordered by updated_at desc by default.
- create_assistant inserts a new assistants row with status='draft' and version=1; display_name must be unique.
- get_assistant fetches by assistants.assistant_id; if not found, return 404.
- update_assistant requires an existing assistant; it increments version by 1 and updates updated_at; status transitions must follow assistants.lifecycle.transitions.
- list_calls returns calls ordered by created_at desc; calls.assistant_id must reference an existing assistant.
- create_call requires assistants.status='active' at time of creation; it inserts calls with status='queued' and direction='outbound'.
- create_call requires exactly one caller-id source: from_phone_number_id OR from_e164_override OR neither (provider default); if from_phone_number_id is used it must reference phone_numbers.status='active'.
- get_call fetches by calls.call_id; if not found, return 404.
- list_phone_numbers returns phone_numbers where status != 'released', ordered by created_at desc.
- get_phone_number fetches by phone_numbers.phone_number_id; if not found, return 404.
- list_tools returns tools where status in ('active','deprecated'), ordered by display_name asc.
- get_tool fetches by tools.tool_id; if not found, return 404.
- assistant_tools rows can only be created/updated for assistants with status in ('draft','active','disabled'); assistants with status='archived' cannot have tool bindings modified.
- A tool with status='disabled' cannot be enabled (assistant_tools.enabled=true) for any assistant.
- Deleting (archiving) an assistant does not delete calls; calls remain immutable audit records once status in ('completed','failed','canceled').