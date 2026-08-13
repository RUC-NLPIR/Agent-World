# Replicate — local MCP environment

This backend stores a catalog of Replicate models (grouped into collections and versions) and an execution ledger of predictions created by API clients. It also tracks lightweight local image-viewer cache entries used to open prediction outputs in a browser, plus audit/quotas needed to list/search models and manage prediction lifecycle (create/get/list/cancel).

Repository: https://github.com/deepfates/mcp-replicate
Homepage: https://smithery.ai/server/mcp-server-replicate

## Datastore

- `api_keys.json` — Replicate API credentials and associated quota/enforcement state for callers of the service. (18 rows; fields: ['id', 'key_hash', 'key_prefix', 'owner_type', 'owner_id', 'status', 'rate_limit_rpm', 'max_concurrent_predictions', 'monthly_spend_limit_usd', 'monthly_spend_used_usd', 'billing_month', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'suspended']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix, owner_type, owner_id)
  - constraint: rate_limit_rpm >= 1 AND rate_limit_rpm <= 6000
  - constraint: max_concurrent_predictions >= 1 AND max_concurrent_predictions <= 1000
- `collections.json` — Curated sets of models (e.g., 'image-generation', 'audio', 'video') used for discovery and listing. (18 rows; fields: ['id', 'slug', 'title', 'description', 'status', 'rank', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'hidden', 'archived']
  - constraint: unique(slug)
  - constraint: rank >= 0
- `models.json` — Model registry entries addressable by owner/name and optionally associated to a collection; includes discoverability metadata and pricing hints. (19 rows; fields: ['id', 'owner', 'name', 'full_name', 'visibility', 'model_type', 'collection_id', 'cover_image_url', 'description', 'tags', 'latest_version_id', 'default_version_id', 'run_count_30d', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: unique(owner, name)
  - constraint: unique(full_name)
  - constraint: run_count_30d >= 0
  - constraint: json_array_length(tags) <= 50
- `model_versions.json` — Immutable model version artifacts with input/output schemas and execution defaults; used to run predictions and to display available versions for a model. (19 rows; fields: ['id', 'model_id', 'vendor_version', 'title', 'description', 'openapi_input_schema', 'openapi_output_schema', 'default_parameters', 'hardware', 'min_runtime_seconds', 'max_runtime_seconds', 'price_per_second_usd', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: unique(model_id, vendor_version)
  - constraint: min_runtime_seconds IS NULL OR min_runtime_seconds >= 0
  - constraint: max_runtime_seconds IS NULL OR max_runtime_seconds >= 1
  - constraint: min_runtime_seconds IS NULL OR max_runtime_seconds IS NULL OR max_runtime_seconds >= min_runtime_seconds
- `predictions.json` — Prediction executions created by clients; stores inputs, lifecycle state, outputs, logs pointers, and cancellation/metrics needed for get/list/cancel. (19 rows; fields: ['id', 'vendor_prediction_id', 'api_key_id', 'model_id', 'model_version_id', 'requested_model_name', 'requested_version', 'input', 'status', 'created_at', 'started_at', 'completed_at', 'updated_at', 'output', 'output_urls', 'error_message', 'logs_url', 'cancel_requested_at', 'canceled_at', 'runtime_seconds', 'cost_usd', 'webhook_url', 'webhook_events_filter'])
  - lifecycle `status`: ['starting', 'processing', 'succeeded', 'failed', 'canceled']
  - constraint: unique(vendor_prediction_id)
  - constraint: runtime_seconds IS NULL OR runtime_seconds >= 0
  - constraint: cost_usd IS NULL OR cost_usd >= 0
  - constraint: json_array_length(output_urls) <= 500
- `image_cache_entries.json` — Local image viewer cache mapping remote URLs to downloaded files and viewer state for view_image/clear_image_cache/cache_stats. (18 rows; fields: ['id', 'url', 'url_sha256', 'content_type', 'byte_size', 'local_path', 'status', 'last_viewed_at', 'downloaded_at', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['cached', 'evicted', 'error']
  - constraint: unique(url_sha256)
  - constraint: byte_size IS NULL OR byte_size >= 0

## Business rules enforced by the tools

- search_models and list_models must only return models where visibility='public' unless the calling api_key.owner_type/owner_id has explicit access (not modeled) to private models.
- list_collections returns collections with status IN ('active','hidden') by default; archived collections are excluded unless an internal flag is set (not exposed by tools).
- get_collection must look up collections by slug or id (implementation choice) and return associated models by models.collection_id.
- get_model must return the model plus all model_versions where model_versions.model_id = models.id ordered by created_at desc; versions with status='disabled' are excluded for non-internal callers.
- create_prediction must accept exactly one of: (a) official model name (mapped to models.full_name via requested_model_name/model_id) or (b) a community model version (mapped via model_versions.vendor_version/model_version_id).
- create_prediction must enforce api_key.status='active', api_key.rate_limit_rpm, and api_key.max_concurrent_predictions by counting predictions where api_key_id matches and status IN ('starting','processing').
- create_prediction must reject requests that would cause api_key.monthly_spend_used_usd to exceed api_key.monthly_spend_limit_usd when the limit is not NULL (use estimated cost if available, otherwise block only once actual cost is known—policy choice must be consistent).
- cancel_prediction is allowed only when predictions.status IN ('starting','processing'); it must set cancel_requested_at and transition status to 'canceled' only when upstream confirms cancellation; otherwise keep status and record error out-of-band.
- get_prediction must retrieve by vendor_prediction_id or internal id (implementation choice) and return status, input, output, logs_url, and timestamps; output may be NULL until succeeded/failed.
- list_predictions must return predictions for the authenticated api_key_id ordered by created_at desc with a default limit (e.g., 20) and maximum limit (e.g., 100).
- When a prediction reaches a terminal state (succeeded/failed/canceled), completed_at must be set and updated_at must advance; runtime_seconds and cost_usd must be non-negative if present.
- view_image must upsert image_cache_entries by url_sha256(url); on successful download store local_path, content_type, byte_size, downloaded_at, set status='cached', and update last_viewed_at each open.
- clear_image_cache must set status='evicted' and null local_path/byte_size/content_type for all entries (or delete rows), and it must be idempotent.
- get_image_cache_stats must compute: total_entries, cached_entries, evicted_entries, error_entries, total_bytes (sum of byte_size where status='cached'), and oldest/newest downloaded_at.