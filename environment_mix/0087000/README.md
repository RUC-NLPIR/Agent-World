# QuickChart Server — local MCP environment

This backend stores chart generation requests made through the QuickChart Server, including full chart configurations, derived render options, and the resulting image artifacts. The main workflow is: accept a chart request (either structured params or full config), normalize it into a canonical Chart.js config, render it via QuickChart, persist the render job and resulting artifact, and (optionally) record a download event to a local filesystem path.

Repository: https://github.com/Magic-Sauce/Quickchart-MCP-Server
Homepage: https://smithery.ai/server/@Magic-Sauce/quickchart-mcp-server

## Datastore

- `api_keys.json` — Represents client credentials used to call the service and apply quota/rate controls. (18 rows; fields: ['id', 'key_hash', 'name', 'status', 'requests_per_minute_limit', 'renders_per_day_limit', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(name)
  - constraint: requests_per_minute_limit BETWEEN 1 AND 6000
  - constraint: renders_per_day_limit BETWEEN 0 AND 100000
- `chart_configs.json` — Canonical chart configuration documents (Chart.js-style) assembled from tool parameters or provided directly. Multiple render jobs may reference the same config via deduplication. (18 rows; fields: ['id', 'config_hash', 'source', 'chart_type', 'labels', 'datasets', 'title', 'options', 'raw_config', 'created_at', 'updated_at'])
  - constraint: unique(config_hash)
  - constraint: chart_type IN ('bar','line','pie','doughnut','radar','polarArea','scatter','bubble','radialGauge','speedometer')
  - constraint: datasets IS NOT NULL
  - constraint: json_array_length(datasets) >= 1
- `render_jobs.json` — A render request/attempt sent to QuickChart, including parameters that affect output and the resulting artifact linkage. (19 rows; fields: ['id', 'api_key_id', 'chart_config_id', 'tool_name', 'status', 'requested_format', 'width', 'height', 'device_pixel_ratio', 'quickchart_url', 'error_message', 'render_started_at', 'render_finished_at', 'artifact_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'rendering', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key (api_key_id) references api_keys(id)
  - constraint: foreign key (chart_config_id) references chart_configs(id)
  - constraint: foreign key (artifact_id) references artifacts(id)
  - constraint: requested_format IN ('png','jpg','webp','svg')
- `artifacts.json` — Rendered chart outputs (binary stored externally or inline), including integrity metadata for caching and downloads. (18 rows; fields: ['id', 'content_sha256', 'content_type', 'byte_size', 'storage_backend', 'storage_ref', 'inline_base64', 'created_at', 'updated_at'])
  - constraint: unique(content_sha256)
  - constraint: byte_size >= 0 AND byte_size <= 50000000
  - constraint: content_type LIKE 'image/%'
  - constraint: storage_backend IN ('inline_base64','filesystem','s3_compatible','memory_cache')
- `download_events.json` — Tracks local downloads performed by the download_chart tool, mapping output paths to render jobs and artifacts for audit and troubleshooting. (19 rows; fields: ['id', 'api_key_id', 'render_job_id', 'artifact_id', 'output_path', 'status', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['started', 'succeeded', 'failed']
  - constraint: foreign key (api_key_id) references api_keys(id)
  - constraint: foreign key (render_job_id) references render_jobs(id)
  - constraint: foreign key (artifact_id) references artifacts(id)
  - constraint: status IN ('started','succeeded','failed')

## Business rules enforced by the tools

- generate_chart(type, labels, datasets, title, options) must be normalized into chart_configs.raw_config with raw_config.type=type, raw_config.data.labels=labels (if provided), raw_config.data.datasets=datasets, and raw_config.options containing at minimum title (if provided) merged with options (if provided).
- download_chart(config, outputPath) must persist chart_configs.raw_config=config, create a render_jobs row with tool_name='download_chart', and create a download_events row with output_path=outputPath that references the render job and the resulting artifact.
- A render_jobs row may only reference an artifact_id after the render completes successfully; setting status to 'succeeded' must be atomic with artifact_id and render_finished_at.
- chart_configs.config_hash must be computed from a canonical JSON normalization (stable key ordering, removed null/undefined fields) so identical configs deduplicate to the same chart_configs row.
- For chart_configs created from generate_chart params: chart_type must equal the tool parameter type and must be one of the allowed chart types; datasets must be a non-empty array and every dataset must include a data array.
- If labels is provided, implementations must enforce either json_array_length(labels)=max length of dataset.data arrays OR allow mismatches only when the underlying chart type supports it; otherwise reject with validation error.
- Per api_key_id, renders_per_day_limit must not be exceeded: counting render_jobs.created_at in the current UTC day where status in ('queued','rendering','succeeded','failed') must be <= renders_per_day_limit.
- Per api_key_id, requests_per_minute_limit must be enforced by counting authenticated tool invocations over a rolling 60-second window (gateway or application layer) and rejecting excess requests before creating render_jobs.
- download_events.output_path must be treated as a server-local path; implementations must reject paths that escape allowed directories (e.g., '..' traversal) and must record status='failed' with error_message when filesystem writes fail.
- Artifacts must be deduplicated by content_sha256: if a newly rendered artifact matches an existing content_sha256, the system should reuse the existing artifacts row and point render_jobs.artifact_id to it.