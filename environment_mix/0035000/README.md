# Stagehand — local MCP environment

Stagehand is a browser-automation backend that maintains stateful browsing sessions and records the sequence of agent-issued commands (navigate/act/extract/observe/screenshot) along with their outputs. The main workflow is: create or resume a session, run tools that append commands to a session timeline, and store resulting page artifacts (extracted text, observed elements, screenshots) for later retrieval/debugging and auditing.

Repository: https://github.com/browserbase/mcp-server-browserbase
Homepage: https://smithery.ai/server/@browserbasehq/mcp-stagehand

## Datastore

- `workspaces.json` — Tenant boundary for API usage. Owns sessions, keys, and enforces quotas. (12 rows; fields: ['id', 'name', 'plan', 'status', 'quota_sessions_per_day', 'quota_commands_per_day', 'quota_screenshots_per_day', 'quota_storage_mb', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'closed']
  - constraint: unique(name)
  - constraint: quota_sessions_per_day >= 0
  - constraint: quota_commands_per_day >= 0
  - constraint: quota_screenshots_per_day >= 0
- `api_keys.json` — API keys used to authenticate and attribute usage to a workspace. (12 rows; fields: ['id', 'workspace_id', 'name', 'key_prefix', 'key_hash', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, key_prefix)
- `browser_sessions.json` — Stateful browser sessions backing Stagehand tool calls. Stores current page state and remote browser allocation metadata. (27 rows; fields: ['id', 'workspace_id', 'api_key_id', 'status', 'browser_provider', 'provider_session_id', 'current_url', 'current_title', 'last_dom_hash', 'last_activity_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['created', 'running', 'ended', 'error']
  - constraint: expires_at is null or expires_at > created_at
  - constraint: current_url is null or length(current_url) <= 4096
- `session_commands.json` — Append-only command log for every tool invocation (navigate/act/extract/observe/screenshot) performed within a session. (34 rows; fields: ['id', 'session_id', 'workspace_id', 'api_key_id', 'tool_name', 'status', 'sequence_no', 'input', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: unique(session_id, sequence_no)
  - constraint: sequence_no >= 1
  - constraint: finished_at is null or started_at is not null
  - constraint: finished_at is null or finished_at >= started_at
- `page_artifacts.json` — Outputs produced by commands: extracted text, observed elements, screenshots, and optional structured metadata. (41 rows; fields: ['id', 'session_id', 'command_id', 'workspace_id', 'artifact_type', 'status', 'content_text', 'elements', 'blob_url', 'mime_type', 'byte_size', 'sha256', 'page_url', 'page_title', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'deleted', 'expired']
  - constraint: byte_size is null or byte_size >= 0
  - constraint: artifact_type != 'screenshot' or blob_url is not null
  - constraint: artifact_type != 'extracted_text' or content_text is not null
  - constraint: artifact_type != 'observed_elements' or elements is not null

## Business rules enforced by the tools

- Every tool invocation creates exactly one session_commands row with tool_name in {stagehand_navigate, stagehand_act, stagehand_extract, stagehand_observe, screenshot}.
- A session_command must belong to exactly one browser_session; workspace_id on session_commands must equal browser_sessions.workspace_id.
- sequence_no is strictly increasing per session; the backend allocates sequence_no atomically and enforces unique(session_id, sequence_no).
- A browser_session in status ended or error must reject new queued commands.
- Command status transitions must follow session_commands.lifecycle.transitions; attempts to skip states (e.g., queued -> succeeded) are rejected.
- For stagehand_extract, the backend must create a page_artifacts row with artifact_type='extracted_text' and non-null content_text when the command succeeds.
- For stagehand_observe, the backend must create a page_artifacts row with artifact_type='observed_elements' and non-null elements when the command succeeds.
- For screenshot, the backend must create a page_artifacts row with artifact_type='screenshot' and non-null blob_url, mime_type='image/png' (or 'image/jpeg') when the command succeeds.
- Workspace quotas are enforced: creating a new browser_session cannot exceed quota_sessions_per_day; enqueuing a command cannot exceed quota_commands_per_day; creating a screenshot artifact cannot exceed quota_screenshots_per_day.
- Artifact retention is enforced by expires_at on sessions and workspace storage cap: when quota_storage_mb is exceeded or session expires, artifacts are transitioned to expired and underlying blobs are deleted; expired/deleted artifacts cannot transition back to available.
- api_keys with status='revoked' cannot create new sessions or enqueue new commands; api_key_id is recorded on sessions/commands whenever authentication is via an API key.
- Deleting/closing a workspace transitions workspace.status to closed and ends all running sessions (browser_sessions.status -> ended) and expires all available artifacts.