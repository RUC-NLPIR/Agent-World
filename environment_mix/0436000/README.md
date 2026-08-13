# SSH Server — local MCP environment

This backend stores named SSH connection credentials (host, username, private key path) and records operational activity performed with them, including SSH command executions and rsync file transfers. The primary workflows are credential CRUD (add/list/remove) and running actions (ssh_exec, rsync_copy) while persisting audit logs, outcomes, and basic lifecycle status.

Repository: https://github.com/KinoThe-Kafkaesque/ssh-mcp-server
Homepage: https://smithery.ai/server/@KinoThe-Kafkaesque/ssh-mcp-server

## Datastore

- `workspaces.json` — Tenant boundary for credentials and operation logs. In many deployments this maps to a single installation, but the backend supports multiple workspaces for separation and future multi-user support. (12 rows; fields: ['id', 'slug', 'display_name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(slug)
  - constraint: slug length between 3 and 64
  - constraint: display_name length between 1 and 128
- `ssh_credentials.json` — Stored SSH credentials referenced by name. Contains host, username, and private key file path; may be used by ssh_exec and rsync_copy. (33 rows; fields: ['id', 'workspace_id', 'name', 'host', 'port', 'username', 'private_key_path', 'host_fingerprint', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(workspace_id, name) WHERE status != 'deleted'
  - constraint: host length between 1 and 255
  - constraint: username length between 1 and 64
  - constraint: private_key_path length between 1 and 4096
- `ssh_command_executions.json` — Audit log of ssh_exec calls and their outcomes. Stores request parameters, lifecycle status, exit code, and captured output (subject to truncation limits). (34 rows; fields: ['id', 'workspace_id', 'credential_id', 'host', 'username', 'private_key_path', 'command', 'status', 'started_at', 'finished_at', 'exit_code', 'stdout', 'stderr', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: host length between 1 and 255
  - constraint: username length between 1 and 64
  - constraint: private_key_path length between 1 and 4096
  - constraint: command length between 1 and 65535
- `rsync_transfers.json` — Audit log of rsync_copy operations, including direction, paths, and outcomes. Uses a stored credential referenced by credentialName. (39 rows; fields: ['id', 'workspace_id', 'credential_id', 'direction', 'local_path', 'remote_path', 'status', 'started_at', 'finished_at', 'bytes_transferred', 'rsync_exit_code', 'output_log', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: direction IN ('toRemote','fromRemote')
  - constraint: local_path length between 1 and 4096
  - constraint: remote_path length between 1 and 4096
  - constraint: bytes_transferred >= 0 (if not null)
- `api_keys.json` — API authentication keys for calling tools, with basic quotas to prevent abuse (command/rsync). (12 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'status', 'allowed_hosts', 'max_execs_per_hour', 'max_rsync_per_hour', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: max_execs_per_hour between 0 and 10000
  - constraint: max_rsync_per_hour between 0 and 10000

## Business rules enforced by the tools

- add_credential(name, host, username, privateKeyPath) inserts into ssh_credentials with status='active' and port=22; it must reject if a non-deleted credential with the same (workspace_id, name) already exists.
- list_credentials returns ssh_credentials for the workspace where status != 'deleted', ordered by created_at asc (or stable by name).
- remove_credential(name) must resolve name within the workspace and then soft-delete by setting status='deleted' (and updated_at), and must not physically delete rows referenced by ssh_command_executions or rsync_transfers.
- ssh_exec(host, command, username, privateKeyPath) must create an ssh_command_executions row with the exact provided parameters; if a matching stored credential exists (same workspace, host, username, private_key_path, status='active'), it may set credential_id, otherwise credential_id remains null.
- rsync_copy(credentialName, localPath, remotePath, direction) must look up an active ssh_credentials row by (workspace_id, name=credentialName); if not found or not active, the operation fails and no rsync transfer is started.
- For ssh_exec and rsync_copy, status must follow declared lifecycle transitions; started_at is set when status becomes 'running', finished_at is set when transitioning to a terminal state (succeeded/failed/cancelled).
- private_key_path must be a non-empty absolute path (server-side validation); operations must fail if the file is missing or not readable by the service user, recording error_message and status='failed'.
- Host allowlisting: if an api_keys.allowed_hosts list is configured, ssh_exec.host and the host referenced by rsync_copy's credential must be in that list, otherwise the request is rejected.
- Quota enforcement: per api key, ssh_exec calls must not exceed max_execs_per_hour and rsync_copy calls must not exceed max_rsync_per_hour; rejected calls are not executed and should still be optionally recorded as failed with error_message indicating rate limit.
- Output capture limits: stdout/stderr/output_log must be truncated to a configured maximum size (e.g., 1–5MB) before persistence to prevent unbounded row growth.