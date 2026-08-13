# Tako — local MCP environment

This backend stores uploaded files and structured datasets submitted for visualization, along with the resulting visualization artifacts. It also tracks user/workspace access via API keys and keeps an audit trail of tool invocations (search and visualization) for troubleshooting, quotas, and billing-style metering.

Repository: https://github.com/TakoData/tako-mcp
Homepage: https://smithery.ai/server/@TakoData/tako-mcp

## Datastore

- `workspaces.json` — Tenant container for API usage, uploaded files, datasets, and visualization jobs. (12 rows; fields: ['id', 'name', 'plan', 'status', 'quota_max_files', 'quota_max_storage_bytes', 'quota_max_visualizations_per_day', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: quota_max_files >= 0
  - constraint: quota_max_storage_bytes >= 0
  - constraint: quota_max_visualizations_per_day >= 0
- `api_keys.json` — API keys used to authenticate tool calls into a workspace and to attribute usage. (17 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'last_used_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
- `uploaded_files.json` — Files uploaded to Tako for later visualization via file_id. Stores metadata and pointer to blob storage. (35 rows; fields: ['id', 'workspace_id', 'uploaded_by_key_id', 'original_filename', 'content_type', 'size_bytes', 'sha256_hex', 'storage_provider', 'storage_bucket', 'storage_key', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['uploaded', 'scanned', 'ready', 'failed', 'deleted']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: fk(uploaded_by_key_id) references api_keys(id) on delete set null
  - constraint: size_bytes >= 0
  - constraint: unique(workspace_id, sha256_hex, size_bytes) where status != 'deleted'
- `datasets.json` — Structured datasets submitted in Tako Data Format for immediate visualization. Stored for audit/debugging and optional reuse. (36 rows; fields: ['id', 'workspace_id', 'submitted_by_key_id', 'format', 'payload_json', 'payload_sha256_hex', 'row_count', 'status', 'validation_errors_json', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'validated', 'invalid', 'deleted']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: fk(submitted_by_key_id) references api_keys(id) on delete set null
  - constraint: row_count is null or row_count >= 0
  - constraint: unique(workspace_id, payload_sha256_hex) where status != 'deleted'
- `tool_runs.json` — Audit log and execution records for all MCP tool calls (search and visualization). Stores inputs/outputs, job state, and derived visualization artifacts. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'tool_name', 'request_json', 'uploaded_file_id', 'dataset_id', 'status', 'started_at', 'ended_at', 'error_code', 'error_message', 'response_json', 'visualization_kind', 'visualization_artifact', 'meter_units', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: fk(api_key_id) references api_keys(id) on delete set null
  - constraint: fk(uploaded_file_id) references uploaded_files(id) on delete set null
  - constraint: fk(dataset_id) references datasets(id) on delete set null

## Business rules enforced by the tools

- Every tool invocation (search_tako, upload_file_to_visualize, visualize_file, visualize_dataset) MUST create a tool_runs row with tool_name set accordingly and request_json captured (even if empty).
- Authentication MUST resolve to exactly one active api_keys row; runs created with revoked keys are rejected; api_keys.workspace_id determines the workspace_id for all created/linked records.
- upload_file_to_visualize: decoded base64 bytes MUST be persisted to blob storage and an uploaded_files row MUST be created with status='uploaded' (then may transition to scanned/ready). The tool response_json MUST include the returned file_id (=uploaded_files.id).
- visualize_file: the referenced uploaded_files row MUST exist, belong to the same workspace, and have status in ('ready','scanned','uploaded'); if status='failed' or 'deleted' the run MUST fail with an error_code. Successful visualization MUST store visualization_artifact and set run status to 'succeeded'.
- visualize_dataset: a datasets row MUST be created with payload_json stored, then validated; if invalid, datasets.status='invalid' and tool_runs.status='failed'. If valid, datasets.status='validated' and a visualization_artifact MUST be produced on success.
- search_tako: each call MUST create a tool_runs row; response_json stores the search result payload returned by the upstream/search subsystem. If the implementation performs no-op search, it still records succeeded with an empty result object.
- Workspace quotas MUST be enforced: (a) number of non-deleted uploaded_files per workspace cannot exceed quota_max_files; (b) total retained bytes across non-deleted uploaded_files plus stored visualization artifacts cannot exceed quota_max_storage_bytes; (c) number of succeeded visualization runs per UTC day cannot exceed quota_max_visualizations_per_day.
- FK integrity MUST be enforced: uploaded_files.workspace_id, datasets.workspace_id, tool_runs.workspace_id must reference an existing workspace; cross-workspace linking (e.g., tool_runs.uploaded_file_id pointing to a file in another workspace) is forbidden.
- Status transitions MUST follow the per-collection lifecycle.transition maps; direct jumps (e.g., queued -> succeeded) are invalid unless applied via an internal admin override not exposed through these tools.
- Deletion is soft for uploaded_files and datasets via status='deleted'; blob objects MAY be asynchronously removed, but storage_key must remain for audit unless workspace is deleted.