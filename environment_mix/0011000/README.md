# Mermaid Diagram Generator — local MCP environment

This backend stores API clients, their authentication keys, and a history of Mermaid diagram generation requests and produced outputs. The main workflow is: a client authenticates with an API key, submits Mermaid syntax plus rendering options, the service renders/returns the requested output format, and the request/output are recorded for auditing, caching, and quota enforcement.

Repository: https://github.com/hustcc/mcp-mermaid
Homepage: https://smithery.ai/server/@hustcc/mcp-mermaid

## Datastore

- `projects.json` — Represents a tenant/workspace (project) owning API keys, quota policy, and diagram generation history. (12 rows; fields: ['id', 'name', 'status', 'plan', 'quota_requests_per_day', 'quota_max_mermaid_chars', 'quota_max_output_bytes', 'retention_days', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: quota_requests_per_day >= 0
  - constraint: quota_max_mermaid_chars >= 1
  - constraint: quota_max_output_bytes >= 1
- `api_keys.json` — API keys used to authenticate requests to generate Mermaid diagrams. Keys belong to a project and can be revoked/rotated. (12 rows; fields: ['id', 'project_id', 'key_prefix', 'key_hash', 'status', 'name', 'last_used_at', 'revoked_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: foreign key (project_id) references projects(id) on delete restrict
  - constraint: unique(project_id, key_prefix)
  - constraint: key_prefix length between 4 and 32
  - constraint: revoked_at is null when status = 'active'
- `diagram_requests.json` — An immutable record of each generate_mermaid_diagram call parameters, validation, and render lifecycle for auditing, caching, and rate limiting. (19 rows; fields: ['id', 'project_id', 'api_key_id', 'status', 'mermaid', 'theme', 'background_color', 'output_type', 'input_sha256', 'mermaid_char_count', 'client_ip', 'user_agent', 'error_code', 'error_message', 'render_started_at', 'render_finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'rendering', 'succeeded', 'failed']
  - constraint: foreign key (project_id) references projects(id) on delete restrict
  - constraint: foreign key (api_key_id) references api_keys(id) on delete restrict
  - constraint: mermaid_char_count >= 1
  - constraint: theme in ('default','base','forest','dark','neutral')
- `diagram_outputs.json` — Stores the rendered output (or points to object storage) for a successful diagram request. One request yields at most one output matching the requested output_type. (19 rows; fields: ['id', 'request_id', 'project_id', 'output_type', 'content_bytes', 'mime_type', 'storage_backend', 'content_base64', 'object_url', 'etag', 'created_at', 'updated_at'])
  - lifecycle `output_type`: ['png', 'svg', 'mermaid']
  - constraint: foreign key (request_id) references diagram_requests(id) on delete cascade
  - constraint: foreign key (project_id) references projects(id) on delete restrict
  - constraint: unique(request_id)
  - constraint: content_bytes >= 0
- `usage_events.json` — Append-only usage ledger for rate limiting, quota enforcement, and analytics. Each generate_mermaid_diagram call produces at least one event. (18 rows; fields: ['id', 'project_id', 'api_key_id', 'request_id', 'event_type', 'billable_units', 'mermaid_chars', 'output_bytes', 'occurred_at', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['request_received', 'render_succeeded', 'render_failed']
  - constraint: foreign key (project_id) references projects(id) on delete restrict
  - constraint: foreign key (api_key_id) references api_keys(id) on delete restrict
  - constraint: foreign key (request_id) references diagram_requests(id) on delete cascade
  - constraint: billable_units >= 0

## Business rules enforced by the tools

- generate_mermaid_diagram must persist a diagram_requests row with fields mapped from parameters: mermaid -> diagram_requests.mermaid, theme -> diagram_requests.theme (default 'default'), backgroundColor -> diagram_requests.background_color (default 'white'), outputType -> diagram_requests.output_type (default 'png').
- diagram_requests.mermaid must have length >= 1 and must not exceed projects.quota_max_mermaid_chars for the owning project; otherwise the request is recorded with status='failed', error_code='VALIDATION_ERROR' or 'QUOTA_EXCEEDED', and no diagram_outputs row is created.
- theme must be one of: default, base, forest, dark, neutral; output_type must be one of: png, svg, mermaid; invalid values fail validation before rendering and produce a failed diagram_requests record.
- Each successful diagram_requests (status='succeeded') must have exactly one diagram_outputs row (unique(request_id)). Failed requests must have zero outputs.
- Quota enforcement: for each project, the sum of usage_events.billable_units where event_type='request_received' and occurred_at is within the project's current UTC day must be <= projects.quota_requests_per_day; if exceeding, the service must return an error and record the request as failed with error_code='QUOTA_EXCEEDED'.
- Output size enforcement: if rendering succeeds but produced size exceeds projects.quota_max_output_bytes, the service must mark the request failed with error_code='OUTPUT_TOO_LARGE' and must not store the output payload.
- Caching/dedup: if a prior diagram_requests exists for the same project with status='succeeded' and the same input_sha256, the service may short-circuit rendering by returning the existing diagram_outputs content and creating a new diagram_requests record referencing the same canonical input (or by reusing the existing request), but must still emit a usage_events row for the new call.
- API key authentication: api_keys.status must be 'active' to accept requests; revoked keys must be rejected and no rendering performed. last_used_at must be updated on successful authentication.