# SSH Server — local MCP environment

This backend stores SSH connection profiles (hosts/users/ports and credential references) and a durable audit log of SSH command executions. The main workflow is: a client submits an execute request, the system resolves credentials, runs the command on the remote host, stores stdout/stderr/exit code, and enforces basic rate limits and redaction rules.

Repository: https://github.com/mfangtao/mcp-ssh-server
Homepage: https://smithery.ai/server/@mfangtao/mcp-ssh-server

## Datastore

- `ssh_targets.json` — Registered SSH endpoints (host/port) that can be used for command execution. Allows reuse and policy enforcement per target. (18 rows; fields: ['id', 'host', 'port', 'display_name', 'status', 'allowed_command_regex', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(host, port)
  - constraint: port between 1 and 65535
  - constraint: host length between 1 and 255
- `ssh_credentials.json` — Credential records for SSH authentication (password or private key). Stored encrypted at rest; only referenced by executions. (18 rows; fields: ['id', 'auth_type', 'username', 'password_ciphertext', 'private_key_ciphertext', 'private_key_fingerprint', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: auth_type in ('password','private_key')
  - constraint: case when auth_type='password' then password_ciphertext is not null and private_key_ciphertext is null end
  - constraint: case when auth_type='private_key' then private_key_ciphertext is not null and password_ciphertext is null end
  - constraint: username length between 1 and 128
- `ssh_connections.json` — Reusable connection profiles combining a target and a credential. Maps directly to the execute tool's connection object fields (host/port/username/password/privateKey) via resolved references. (18 rows; fields: ['id', 'target_id', 'credential_id', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(target_id, credential_id)
  - constraint: fk(target_id) references ssh_targets(id) on delete restrict
  - constraint: fk(credential_id) references ssh_credentials(id) on delete restrict
- `ssh_command_executions.json` — Append-only audit log of SSH command execution requests and results. Stores a normalized copy of tool inputs (host/port/username and whether password/privateKey was provided) and the command, plus stdout/stderr/exit code. (19 rows; fields: ['id', 'connection_id', 'host', 'port', 'username', 'auth_provided', 'password_present', 'private_key_present', 'command', 'status', 'requested_at', 'started_at', 'finished_at', 'timeout_seconds', 'exit_code', 'stdout', 'stderr', 'stdout_truncated', 'stderr_truncated', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'timed_out', 'cancelled']
  - constraint: port between 1 and 65535
  - constraint: timeout_seconds between 1 and 3600
  - constraint: length(command) between 1 and 16384
  - constraint: auth_provided in ('none','password','private_key','both')
- `ssh_rate_limits.json` — Server-enforced throttling rules per host/username to prevent abuse (e.g., too many connections or executions). (18 rows; fields: ['id', 'host', 'username', 'window_seconds', 'max_executions', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(host, coalesce(username, ''))
  - constraint: window_seconds between 1 and 86400
  - constraint: max_executions between 1 and 100000

## Business rules enforced by the tools

- execute_ssh_command.connection.host maps to ssh_command_executions.host; connection.port maps to ssh_command_executions.port (default 22 when omitted); connection.username maps to ssh_command_executions.username; command maps to ssh_command_executions.command.
- The raw values of connection.password and connection.privateKey must never be stored in ssh_command_executions; only presence booleans are allowed. If credentials are persisted, they must be stored only in ssh_credentials as ciphertext fields.
- If both password and privateKey are provided, auth_provided must be 'both'; if neither is provided, auth_provided must be 'none' and the execution must be rejected unless a saved ssh_connections profile supplies credentials (implementation may resolve connection_id by (host,port,username) to an active profile).
- An execution may only start if the resolved target (by (host,port) or via connection_id->target_id) is in status='active' and any resolved credential is status='active'.
- Rate limit enforcement: for any incoming execution, count ssh_command_executions with matching host and (username if rule.username is set) and requested_at within window_seconds for active ssh_rate_limits; reject if count >= max_executions.
- Command policy enforcement: if an active ssh_target has allowed_command_regex set, then ssh_command_executions.command must match it or the execution is rejected and recorded with status='failed' and a sanitized error_message.
- Lifecycle enforcement: ssh_command_executions.status transitions must follow the declared transition map; finished_at must be non-null iff status in ('succeeded','failed','timed_out','cancelled'); exit_code may be non-null only for terminal statuses.
- Output truncation: stdout/stderr must be truncated to a configured maximum size (e.g., 64KB each) with stdout_truncated/stderr_truncated set accordingly.
- Port must be within 1..65535; timeout_seconds must be within 1..3600 for every execution.