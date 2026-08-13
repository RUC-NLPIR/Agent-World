# Replicate Flux MCP — local MCP environment

This backend stores Replicate-based generation requests (predictions) and their produced artifacts (images/SVGs), grouped into user-visible "jobs" such as single-image generation, multi-prompt batches, and variant sets. The main workflow is: create a generation job -> create one or more Replicate predictions -> poll/get prediction status -> persist outputs and expose recent prediction history.

Repository: https://github.com/awkoy/replicate-flux-mcp
Homepage: https://smithery.ai/server/@awkoy/replicate-flux-mcp

## Datastore

- `api_keys.json` — API keys used to authenticate callers to the MCP service, track ownership, and enforce quotas/rate limits. (12 rows; fields: ['id', 'key_hash', 'name', 'status', 'last_used_at', 'daily_request_quota', 'daily_compute_ms_quota', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: daily_request_quota >= 0
  - constraint: daily_compute_ms_quota >= 0
- `generation_jobs.json` — User-visible generation intents initiated via tools (single image, multiple images, variants, SVG). A job may map to one or more Replicate predictions. (23 rows; fields: ['id', 'api_key_id', 'tool_name', 'model_provider', 'model_ref', 'job_type', 'input', 'requested_outputs', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: requested_outputs >= 1
  - constraint: fk(api_key_id) references api_keys(id)
  - constraint: tool_name in ('generate_image','generate_multiple_images','generate_image_variants','generate_svg','create_prediction')
  - constraint: job_type in ('single_image','multi_prompt_batch','variants','svg','raw_prediction')
- `replicate_predictions.json` — Replicate prediction records created and tracked by the service. Supports create_prediction, get_prediction, and prediction_list tools. (39 rows; fields: ['id', 'job_id', 'api_key_id', 'replicate_prediction_id', 'replicate_model_ref', 'input', 'status', 'replicate_created_at', 'replicate_completed_at', 'logs', 'error_message', 'metrics', 'created_at', 'updated_at'])
  - lifecycle `status`: ['starting', 'processing', 'succeeded', 'failed', 'canceled']
  - constraint: unique(replicate_prediction_id)
  - constraint: fk(api_key_id) references api_keys(id)
  - constraint: fk(job_id) references generation_jobs(id)
  - constraint: replicate_completed_at is null OR replicate_created_at is null OR replicate_completed_at >= replicate_created_at
- `prediction_outputs.json` — Outputs produced by a Replicate prediction: image URLs, SVG text, or other artifact references. Used to return results for generate_image/generate_svg and batch/variant tools. (31 rows; fields: ['id', 'prediction_id', 'output_index', 'artifact_type', 'url', 'text', 'json_payload', 'content_type', 'byte_size', 'created_at', 'updated_at'])
  - lifecycle `artifact_type`: ['image_url', 'svg_text', 'file_url', 'json']
  - constraint: fk(prediction_id) references replicate_predictions(id)
  - constraint: unique(prediction_id, output_index)
  - constraint: output_index >= 0
  - constraint: byte_size is null OR byte_size >= 0
- `usage_events.json` — Immutable usage ledger for quota enforcement and auditing per API key and tool call. Records the associated job/prediction and compute metrics. (39 rows; fields: ['id', 'api_key_id', 'tool_name', 'job_id', 'prediction_id', 'request_payload', 'response_summary', 'compute_ms', 'created_at', 'updated_at'])
  - lifecycle `tool_name`: ['generate_image', 'generate_multiple_images', 'generate_image_variants', 'generate_svg', 'get_prediction', 'create_prediction', 'prediction_list']
  - constraint: fk(api_key_id) references api_keys(id)
  - constraint: fk(job_id) references generation_jobs(id)
  - constraint: fk(prediction_id) references replicate_predictions(id)
  - constraint: compute_ms >= 0

## Business rules enforced by the tools

- Every tool invocation must authenticate to exactly one api_keys row with status='active'; otherwise reject.
- generate_image creates exactly one generation_jobs row with job_type='single_image' and requested_outputs=1, and creates at least one replicate_predictions row linked to that job.
- generate_multiple_images creates one generation_jobs row with job_type='multi_prompt_batch'; requested_outputs must equal the number of prompts in generation_jobs.input.prompts (array).
- generate_image_variants creates one generation_jobs row with job_type='variants'; requested_outputs must equal generation_jobs.input.num_variants (integer >= 1).
- generate_svg creates one generation_jobs row with job_type='svg' and must use model_ref indicating a Recraft SVG-capable model; outputs must include at least one prediction_outputs row with artifact_type='svg_text' (or content_type='image/svg+xml').
- create_prediction creates one generation_jobs row with job_type='raw_prediction' and exactly one replicate_predictions row; the replicate_predictions.input must be identical to the payload sent to Replicate.
- get_prediction must retrieve by replicate_predictions.replicate_prediction_id (preferred) or internal replicate_predictions.id; the response must include replicate_predictions.status, input, error_message, logs (if allowed), and all prediction_outputs for that prediction.
- prediction_list returns replicate_predictions rows ordered by created_at desc (or replicate_created_at when present) and may be scoped to the calling api_key_id; it must not return predictions belonging to other api keys.
- A replicate_predictions.status update must follow the declared transitions; when it reaches succeeded/failed/canceled, it is terminal and immutable except for late-arriving logs/metrics.
- generation_jobs.status must be derived from child replicate_predictions: queued if none started, running if any starting/processing, succeeded only if all linked predictions succeeded, failed if any failed (unless explicitly cancelled), cancelled only by explicit user/system cancel.
- prediction_outputs may only be inserted/updated when the owning replicate_predictions.status is in ('processing','succeeded'); once prediction is terminal, outputs are append-only (no deletions), except to redact sensitive URLs if required.
- Quota enforcement: for each api_key_id, total usage_events count in the last 24 hours must be <= api_keys.daily_request_quota, and sum(usage_events.compute_ms) in the last 24 hours must be <= api_keys.daily_compute_ms_quota; otherwise reject mutating tools (generate_* and create_prediction).
- Each successful tool call must insert one usage_events row capturing tool_name and linking job_id/prediction_id when applicable; compute_ms must be 0 for read-only tools (get_prediction, prediction_list) unless explicitly configured otherwise.
- replicate_predictions.replicate_prediction_id must be unique across the service to prevent mixing outputs/status between different Replicate predictions.