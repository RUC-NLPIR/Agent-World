# MasterGo Magic — local MCP environment

MasterGo Magic stores design-file extraction sessions and their retrieved artifacts (DSL, site/page meta, component documentation links, and generator workflows) so clients can iteratively generate frontend code from MasterGo design layers. The main workflow is: create a session for a file/layer, fetch DSL/meta, follow componentDocumentLinks to fetch component docs, and optionally fetch a generator workflow saved into a workspace root path.

Repository: https://github.com/mastergo-design/mastergo-magic-mcp
Homepage: https://smithery.ai/server/@mastergo-design/mastergo-magic-mcp

## Datastore

- `workspaces.json` — Tenant/workspace representing a user's project environment where generator workflow files are written. Also groups sessions and enforces path and quota constraints. (12 rows; fields: ['id', 'name', 'owner_subject', 'default_root_path', 'status', 'quota_sessions_per_day', 'quota_fetches_per_day', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(owner_subject, name)
  - constraint: quota_sessions_per_day >= 0
  - constraint: quota_fetches_per_day >= 0
  - constraint: default_root_path is null OR (default_root_path starts with '/' AND NOT contains '\0')
- `design_files.json` — MasterGo design file references known to the backend. Used to cache metadata and provide FK targets for session requests that supply fileId. (12 rows; fields: ['id', 'workspace_id', 'external_file_id', 'name', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'revoked']
  - constraint: unique(workspace_id, external_file_id)
  - constraint: external_file_id != ''
- `design_sessions.json` — A request/analysis session scoped to a specific fileId and layerId. Tool calls (getDsl/getMeta/getComponentLink/getComponentGenerator) are recorded against a session for auditability and caching. (17 rows; fields: ['id', 'workspace_id', 'design_file_id', 'external_file_id', 'external_layer_id', 'status', 'last_activity_at', 'expires_at', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'completed', 'failed', 'expired']
  - constraint: external_file_id != ''
  - constraint: external_layer_id is null OR external_layer_id != ''
  - constraint: expires_at is null OR expires_at > created_at
  - constraint: FK: design_sessions.workspace_id = design_files.workspace_id via design_file_id
- `session_artifacts.json` — Materialized outputs returned by the tools: raw DSL JSON, meta rules markdown and results JSON, component doc pages fetched from componentDocumentLinks, and generator workflow payloads written to disk under a rootPath. (20 rows; fields: ['id', 'session_id', 'artifact_type', 'status', 'source_tool', 'external_url', 'sequence_index', 'root_path', 'content_json', 'content_markdown', 'content_text', 'content_sha256', 'error_code', 'error_message', 'fetched_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'ready', 'error', 'expired']
  - constraint: unique(session_id, artifact_type, external_url) WHERE artifact_type = 'component_doc'
  - constraint: unique(session_id, artifact_type) WHERE artifact_type IN ('dsl','meta_rules_md','meta_results_json','generator_workflow')
  - constraint: sequence_index is null OR sequence_index >= 0
  - constraint: root_path is null OR (root_path starts with '/' AND NOT contains '\0')
- `tool_invocations.json` — Immutable audit log of each tool call (including version tool), used for troubleshooting, rate limiting, and reproducing outputs. Links to any produced artifact(s). (19 rows; fields: ['id', 'workspace_id', 'session_id', 'tool_name', 'request_params', 'resolved_external_file_id', 'resolved_external_layer_id', 'resolved_root_path', 'http_status', 'duration_ms', 'result_status', 'error_code', 'error_message', 'produced_artifact_ids', 'created_at', 'updated_at'])
  - lifecycle `result_status`: ['ok', 'error', 'rate_limited']
  - constraint: duration_ms is null OR duration_ms >= 0
  - constraint: http_status is null OR (http_status >= 100 AND http_status <= 599)
  - constraint: request_params must be a JSON object (can be {})
  - constraint: produced_artifact_ids elements must FK to session_artifacts.id

## Business rules enforced by the tools

- A workspace in status 'deleted' must not allow new tool invocations; existing sessions/artifacts may be read only for a limited retention window.
- For mcp__getDsl and mcp__getMeta, the backend must resolve a concrete (external_file_id, external_layer_id) either from request context or an existing design_session; resolved_external_file_id must be non-empty.
- Calling mcp__getDsl creates/updates exactly one session_artifacts row with artifact_type='dsl' for the target session; status becomes 'ready' only if content_json is non-null.
- Calling mcp__getMeta creates/updates exactly two artifacts for the target session: artifact_type='meta_rules_md' (content_markdown non-null) and artifact_type='meta_results_json' (content_json non-null).
- Calling mcp__getComponentLink iterates componentDocumentLinks sequentially and writes one session_artifacts row per URL with artifact_type='component_doc', unique by (session_id, external_url); sequence_index must reflect the link's position in the array.
- Calling mcp__getComponentGenerator requires an absolute rootPath; the service must reject paths that are not absolute, contain null bytes, or escape the workspace boundary when joined with generated relative file paths.
- Per workspace, the system must enforce quota_sessions_per_day for newly created design_sessions and quota_fetches_per_day for tool_invocations excluding the version tool; if exceeded, tool_invocations.result_status='rate_limited' and no artifacts may transition to 'ready'.
- A design_session in status 'expired' must not transition back to 'active'; new fetches for the same file/layer must create a new session.
- If an artifact is marked 'expired', it must never transition back to 'ready'; a fresh artifact row must be created for new content when TTL has passed.
- The version_0.0.4-beta.11 tool must record a tool_invocations row with tool_name='version_0.0.4-beta.11' and request_params='{}'; it must not create a design_session.