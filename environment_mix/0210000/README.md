# Super Shell — local MCP environment

Super Shell stores a policy-controlled catalog of shell commands (a whitelist) and an auditable execution log. Commands can be marked safe, require approval (creating pending approval requests), or forbidden; admins can approve/deny pending requests, and all executions are recorded with status, outputs, and platform context.

Repository: https://github.com/cfdude/super-shell-mcp
Homepage: https://smithery.ai/server/@cfdude/super-shell-mcp

## Datastore

- `platform_instances.json` — Represents the running host/runtime where Super Shell executes commands (OS, shell, architecture). Used by get_platform_info and to stamp executions with environment details. (12 rows; fields: ['id', 'hostname', 'os_name', 'os_version', 'arch', 'default_shell', 'shell_version', 'status', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'retired']
  - constraint: required(os_name, default_shell, status, created_at, updated_at)
  - constraint: status in ('active','retired')
  - constraint: last_seen_at >= created_at (if last_seen_at is not null)
- `whitelist_commands.json` — Canonical registry of commands and their security policy (safe / requires_approval / forbidden). Powers get_whitelist, add_to_whitelist, update_security_level, remove_from_whitelist. (31 rows; fields: ['id', 'command', 'normalized_command', 'security_level', 'description', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(normalized_command) where status='active'
  - constraint: required(command, normalized_command, security_level, status, created_at, updated_at)
  - constraint: security_level in ('safe','requires_approval','forbidden')
  - constraint: status='deleted' implies deleted_at is not null
- `approval_requests.json` — Pending approval workflow items created when a command requiring approval is requested/executed. Powers get_pending_commands, approve_command, deny_command. (26 rows; fields: ['id', 'whitelist_command_id', 'requested_command', 'requested_args', 'status', 'denial_reason', 'requested_at', 'reviewed_at', 'reviewed_by', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'approved', 'denied', 'expired', 'cancelled']
  - constraint: required(id, requested_command, status, requested_at, created_at, updated_at)
  - constraint: status in ('pending','approved','denied','expired','cancelled')
  - constraint: status='denied' implies denial_reason is not null
  - constraint: status in ('approved','denied','expired','cancelled') implies reviewed_at is not null OR status in ('expired','cancelled') may set reviewed_at
- `command_executions.json` — Audit log of every execute_command call, including inputs, outputs, exit codes, and policy decisions. (32 rows; fields: ['id', 'platform_instance_id', 'whitelist_command_id', 'approval_request_id', 'command', 'args', 'policy_decision', 'status', 'exit_code', 'stdout', 'stderr', 'started_at', 'finished_at', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'blocked']
  - constraint: required(id, platform_instance_id, command, policy_decision, status, created_at, updated_at)
  - constraint: fk(platform_instance_id) references platform_instances.id
  - constraint: fk(whitelist_command_id) references whitelist_commands.id
  - constraint: fk(approval_request_id) references approval_requests.id

## Business rules enforced by the tools

- get_platform_info returns the single active platform_instances row for the running service; if none exists it is created with status='active' and last_seen_at=now().
- get_whitelist returns whitelist_commands where status='active'.
- add_to_whitelist upserts by normalized_command when an active row exists: it updates security_level/description and bumps updated_at; otherwise it inserts a new active row.
- update_security_level requires an existing active whitelist_commands row for the given command (matched by normalized_command); it updates security_level and updated_at.
- remove_from_whitelist performs a soft delete: whitelist_commands.status transitions active->deleted and sets deleted_at=now(); the normalized_command uniqueness applies only to active rows.
- execute_command always inserts a command_executions row. It resolves whitelist_commands by normalized_command (active only) and sets whitelist_command_id when found.
- If no active whitelist entry exists, execute_command sets policy_decision='blocked_not_whitelisted', status='blocked', finished_at=now(), and does not run the command.
- If whitelist_commands.security_level='forbidden', execute_command sets policy_decision='blocked_forbidden', status='blocked', finished_at=now(), and does not run the command.
- If whitelist_commands.security_level='safe', execute_command sets policy_decision='allowed' and runs the command, transitioning status queued->running->(succeeded|failed) and recording stdout/stderr/exit_code/timestamps.
- If whitelist_commands.security_level='requires_approval', execute_command creates an approval_requests row with status='pending' (and links approval_request_id on the execution), sets policy_decision='pending_approval', status='blocked', finished_at=now(), and does not run the command.
- get_pending_commands returns approval_requests where status='pending' and (expires_at is null OR expires_at > now()). If expires_at <= now(), the system must transition the request to status='expired'.
- approve_command(commandId) transitions approval_requests.status pending->approved, sets reviewed_at=now(); subsequent executions referencing that approval_request_id must treat policy_decision as 'allowed' only if the referenced request is approved and not expired.
- deny_command(commandId, reason) transitions approval_requests.status pending->denied, sets denial_reason=reason and reviewed_at=now(); subsequent executions must not run when linked to denied requests and should use policy_decision='blocked_denied'.
- An approval_requests row cannot transition out of a terminal state (approved/denied/expired/cancelled).
- For any execution row, stdout/stderr storage must be truncated to a configured maximum (e.g., 1MB each) and the stored values must reflect truncation if applied.
- Arguments arrays (execute_command.args and approval_requests.requested_args) must contain only strings; null is treated as an empty list.