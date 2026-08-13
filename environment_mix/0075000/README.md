# OpenRouter MCP Server — local MCP environment

This backend powers an MCP server façade over OpenRouter: it maintains a local catalog of models mirrored from OpenRouter, and records chat completion requests/responses for audit, debugging, and cost tracking. Primary workflows are (1) listing/filtering models and fetching model details/validation and (2) issuing chat completions against a selected model while persisting request metadata, lifecycle, and usage.

Repository: https://github.com/heltonteixeira/openrouterai
Homepage: https://smithery.ai/server/@mcpserver/openrouterai

## Datastore

- `api_keys.json` — API keys used by clients to call this MCP server and the upstream OpenRouter key/credentials used to execute requests. Supports authentication, rotation, quota enforcement, and audit. (12 rows; fields: ['id', 'key_type', 'key_hash', 'key_prefix', 'label', 'status', 'rate_limit_rpm', 'monthly_spend_cap_usd', 'monthly_spend_used_usd', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix, key_type) -- best-effort uniqueness for display; collisions allowed only if forced by manual override
  - constraint: rate_limit_rpm >= 1 and rate_limit_rpm <= 100000
  - constraint: monthly_spend_used_usd >= 0
- `models.json` — Local mirror of OpenRouter model catalog for fast search, validation, and detail retrieval. (18 rows; fields: ['id', 'model_id', 'name', 'provider', 'description', 'context_length', 'max_output_tokens', 'pricing_prompt_usd_per_1k', 'pricing_completion_usd_per_1k', 'capabilities', 'tags', 'status', 'upstream_updated_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: unique(model_id)
  - constraint: context_length is null or context_length >= 1
  - constraint: max_output_tokens is null or max_output_tokens >= 1
  - constraint: pricing_prompt_usd_per_1k is null or pricing_prompt_usd_per_1k >= 0
- `model_aliases.json` — Alternate IDs and legacy identifiers that should validate as the same model. Used by validate_model and get_model_info resolution. (18 rows; fields: ['id', 'model_id', 'alias', 'alias_type', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(alias)
  - constraint: fk(model_id) references models(id) on delete cascade
- `chat_completions.json` — Each chat completion call executed through the MCP tool, including request payload, model resolution, lifecycle, and token/cost usage for reporting and quota enforcement. (20 rows; fields: ['id', 'client_api_key_id', 'upstream_api_key_id', 'requested_model', 'resolved_model_id', 'request_payload', 'response_payload', 'status', 'error_code', 'error_message', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'cost_usd', 'latency_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(client_api_key_id) references api_keys(id) on delete set null
  - constraint: fk(upstream_api_key_id) references api_keys(id) on delete set null
  - constraint: fk(resolved_model_id) references models(id) on delete set null
  - constraint: prompt_tokens is null or prompt_tokens >= 0
- `model_catalog_sync_jobs.json` — Tracks background syncs that refresh the local model catalog from upstream OpenRouter. Ensures search_models/get_model_info/validate_model have data even if upstream is rate-limited. (18 rows; fields: ['id', 'trigger', 'status', 'started_at', 'finished_at', 'models_upserted', 'models_disabled', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: models_upserted >= 0
  - constraint: models_disabled >= 0
  - constraint: finished_at is null or started_at is not null
  - constraint: status = 'succeeded' implies finished_at is not null

## Business rules enforced by the tools

- search_models reads from models where status != 'disabled' by default; optional server-side configuration may include disabled models for admin keys only (api_keys.key_type='client' with elevated label/flag out-of-band).
- get_model_info must resolve the input identifier by first matching models.model_id, then model_aliases.alias (status='active'), returning the linked models row; if no match, return not found.
- validate_model returns valid=true if and only if the identifier resolves to a models row with status in ('active','deprecated'); valid=false otherwise.
- chat_completion must create a chat_completions row in status='queued' before calling upstream; it transitions queued->running when the upstream request starts and to succeeded/failed on completion; it may be cancelled only before succeeded/failed.
- chat_completion must validate/resolve requested_model using the same logic as validate_model; if invalid, mark the chat_completions row failed with error_code='invalid_model' and do not call upstream.
- For any call authenticated with a client api key, enforce api_keys.status='active', rate limits (rate_limit_rpm), and if monthly_spend_cap_usd is set, deny or fail requests that would cause monthly_spend_used_usd + estimated_cost_usd > monthly_spend_cap_usd.
- When a chat_completion succeeds, persist response_payload, token counts, and cost_usd (from upstream when available, otherwise computed from models pricing fields); then increment api_keys.monthly_spend_used_usd atomically for the calling client_api_key_id.
- Model catalog should be kept fresh: if the newest model_catalog_sync_jobs.succeeded.finished_at is older than a configured TTL, search_models/get_model_info/validate_model may enqueue an on_demand sync job but must still serve from the last known models snapshot to avoid blocking tool calls.
- model_aliases.alias must be globally unique and must not equal any existing models.model_id (enforced by application-level constraint check on insert/update).