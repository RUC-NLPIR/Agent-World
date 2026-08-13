# Eraser Diagram Generator — local MCP environment

This backend stores requests to generate Eraser diagrams and the resulting diagram artifacts produced by a generator service. The main workflow is: a client submits a generation request, the system runs a job to produce an Eraser-compatible output, stores the artifact(s), and records usage for auditing and operational troubleshooting.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@dravidsajinraj-iex/ai-diagram-generator-mcp

## Datastore

- `projects.json` — Logical container for diagram generation activity; groups multiple generations under one project/workspace concept for retention, access control, and organization. (12 rows; fields: ['id', 'name', 'description', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(name) where status != 'deleted'
  - constraint: name length between 1 and 200
- `diagram_generations.json` — A request/attempt to generate an Eraser diagram. This is the primary entity mutated by the generateDiagram tool (creates a generation job with default settings). (18 rows; fields: ['id', 'project_id', 'status', 'requested_by_api_key_id', 'generator_version', 'input_spec', 'idempotency_key', 'queued_at', 'started_at', 'finished_at', 'error_code', 'error_message', 'compute_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(project_id) references projects(id) on delete restrict
  - constraint: foreign key(requested_by_api_key_id) references api_keys(id) on delete set null
  - constraint: compute_ms is null or compute_ms >= 0
  - constraint: error_code is null iff status != 'failed'
- `diagram_artifacts.json` — Outputs produced by a generation (e.g., Eraser diagram DSL, JSON, image preview). Multiple artifacts can be attached to one generation. (18 rows; fields: ['id', 'generation_id', 'artifact_type', 'content_mime_type', 'content_text', 'content_blob_url', 'bytes', 'checksum_sha256', 'created_at', 'updated_at'])
  - lifecycle `artifact_type`: ['eraser_diagram_dsl', 'eraser_json', 'png_preview', 'svg_preview', 'log']
  - constraint: foreign key(generation_id) references diagram_generations(id) on delete cascade
  - constraint: bytes >= 0
  - constraint: exactly one of (content_text, content_blob_url) must be non-null
  - constraint: unique(generation_id, artifact_type)
- `api_keys.json` — API keys used to access the diagram generator service and attribute usage. (12 rows; fields: ['id', 'key_hash', 'label', 'status', 'rate_limit_per_minute', 'daily_generation_quota', 'created_at', 'updated_at', 'revoked_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: rate_limit_per_minute between 1 and 6000
  - constraint: daily_generation_quota between 0 and 100000
  - constraint: revoked_at is not null iff status = 'revoked'
- `usage_events.json` — Append-only usage ledger for auditing, throttling, and billing; records each generateDiagram invocation and its outcome. (18 rows; fields: ['id', 'api_key_id', 'generation_id', 'tool_name', 'request_ts', 'response_status', 'latency_ms', 'created_at', 'updated_at'])
  - lifecycle `response_status`: ['accepted', 'rejected_quota', 'rejected_rate_limit', 'error']
  - constraint: foreign key(api_key_id) references api_keys(id) on delete set null
  - constraint: foreign key(generation_id) references diagram_generations(id) on delete cascade
  - constraint: latency_ms is null or latency_ms >= 0
  - constraint: index(api_key_id, request_ts)

## Business rules enforced by the tools

- generateDiagram creates a new diagram_generations row with input_spec = {} (empty object) because the tool surface defines no parameters.
- On generateDiagram, if an API key is provided and status != 'active', the request must be rejected and a usage_events row recorded with response_status = 'error' or 'rejected_quota' as appropriate.
- Rate limiting: for a given api_key_id, the number of usage_events with tool_name='generateDiagram' and response_status='accepted' in the last 60 seconds must be <= api_keys.rate_limit_per_minute; otherwise record response_status='rejected_rate_limit' and do not enqueue a generation.
- Daily quota: for a given api_key_id, the count of accepted generateDiagram usage_events in the current UTC day must be < api_keys.daily_generation_quota; otherwise record response_status='rejected_quota' and do not enqueue a generation.
- A generation may only move through the declared status transitions; direct transitions such as queued -> succeeded are invalid.
- When a generation reaches status='succeeded', at least one diagram_artifacts row must exist for that generation, and one of them should have artifact_type in ('eraser_diagram_dsl','eraser_json').
- When a generation reaches status='failed', error_code and error_message must be set and no new non-log artifacts may be added afterward.
- diagram_artifacts must store content either inline (content_text) or in object storage (content_blob_url) but never both and never neither.
- Idempotency: if idempotency_key is supplied, repeated generateDiagram calls within the same project_id must return/attach to the existing diagram_generations row instead of creating a new one.