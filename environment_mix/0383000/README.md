# Kroki Server — local MCP environment

This backend stores requests to render Kroki diagrams from source text (Mermaid/PlantUML/etc.), the derived render URLs, and optional persisted binary outputs when a diagram is downloaded to a file. Main workflows are: (1) create a render request and compute a deterministic Kroki URL for it, and (2) render and store an artifact for download/export with optional SVG scaling.

Repository: https://github.com/tkoba1974/mcp-kroki
Homepage: https://smithery.ai/server/@tkoba1974/mcp-kroki

## Datastore

- `diagram_types.json` — Catalog of supported diagram syntaxes and output formats for Kroki rendering. Used to validate incoming tool requests and to version/disable types without code changes. (25 rows; fields: ['id', 'type_key', 'display_name', 'enabled', 'default_output_format', 'allowed_output_formats', 'created_at', 'updated_at'])
  - lifecycle `enabled`: [True, False]
  - constraint: unique(type_key)
  - constraint: type_key length between 1 and 64
  - constraint: allowed_output_formats is non-empty
  - constraint: default_output_format must be contained in allowed_output_formats
- `diagram_requests.json` — Immutable-ish request records representing a user's desire to render a diagram from source content in a specific type and output format. Used by both tools: URL generation and download/export. (36 rows; fields: ['id', 'diagram_type_id', 'type_key', 'content', 'content_sha256', 'output_format', 'kroki_base_url', 'encoded_payload', 'render_url', 'status', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['created', 'url_generated', 'rendered', 'failed']
  - constraint: FK(diagram_type_id) references diagram_types(id) on delete restrict
  - constraint: type_key must equal diagram_types.type_key at insertion time
  - constraint: output_format must be in diagram_types.allowed_output_formats at insertion time
  - constraint: content length between 1 and 500000
- `download_jobs.json` — Represents a request to fetch/render a diagram and save it to a local path. Tracks requested path/format/scale and the resulting stored artifact metadata. (33 rows; fields: ['id', 'diagram_request_id', 'output_path', 'output_format', 'scale', 'apply_scale', 'status', 'http_status', 'bytes_written', 'mime_type', 'started_at', 'completed_at', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'rendering', 'writing', 'completed', 'failed', 'cancelled']
  - constraint: FK(diagram_request_id) references diagram_requests(id) on delete restrict
  - constraint: scale >= 0.1
  - constraint: if output_format != 'svg' then apply_scale must be false
  - constraint: bytes_written >= 0 when not null
- `render_cache.json` — Optional server-side cache of rendered outputs to avoid refetching from Kroki for identical requests and to support quick repeated downloads. Stores small artifacts inline or via a storage pointer. (36 rows; fields: ['id', 'diagram_request_id', 'output_format', 'etag', 'sha256', 'byte_size', 'storage_kind', 'content_inline_base64', 'storage_uri', 'status', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'evicted']
  - constraint: FK(diagram_request_id) references diagram_requests(id) on delete cascade
  - constraint: unique(diagram_request_id, output_format)
  - constraint: byte_size >= 0
  - constraint: if storage_kind = 'inline' then content_inline_base64 is not null and storage_uri is null

## Business rules enforced by the tools

- generate_diagram_url must create (or reuse via unique(type_key, output_format, content_sha256, kroki_base_url)) a diagram_requests row with status transitioning created -> url_generated and return diagram_requests.render_url.
- generate_diagram_url must reject requests where diagram_types.enabled=false or outputFormat not in diagram_types.allowed_output_formats (when outputFormat is omitted, use diagram_types.default_output_format).
- download_diagram must create a diagram_requests row (or reuse an existing one) and then create a download_jobs row with output_path from outputPath, output_format from outputFormat or derived from output_path extension, and scale defaulting to 1.0.
- download_diagram must enforce scale >= 0.1; if output_format != 'svg' then scale must be stored but apply_scale must be false and no SVG dimension mutation attempted.
- download_jobs status transitions must follow the declared transitions; on any failure, set status=failed and populate last_error; on success set status=completed, bytes_written, mime_type, completed_at.
- When a render is successfully fetched, the implementation may upsert render_cache for (diagram_request_id, output_format) with sha256 and byte_size; cache entries must not exceed 10MB inline, otherwise use storage_uri and non-inline storage_kind.
- output_format must always be one of the declared enums; base64 is allowed only for URL generation/caching and must not be used as a download_jobs.output_format.