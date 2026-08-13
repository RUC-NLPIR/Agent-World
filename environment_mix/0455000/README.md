# Windows Command Line MCP Server — local MCP environment

This backend stores configuration for a Windows Command Line MCP Server (allowed commands/policies) and an audit log of tool invocations and command executions. The primary workflows are: clients authenticate with an API key, call read-only inventory tools (processes/system/network/tasks/services), and optionally execute allow-listed commands or PowerShell while enforcing timeouts, working directory policies, and quotas.

Repository: https://github.com/alxspiker/Windows-Command-Line-MCP-Server
Homepage: https://smithery.ai/server/@alxspiker/Windows-Command-Line-MCP-Server

## Datastore

- `api_keys.json` — Client credentials used to authenticate MCP tool calls and apply per-key quotas/policies. (18 rows; fields: ['id', 'key_hash', 'name', 'status', 'allowed_command_set_id', 'rate_limit_per_minute', 'max_concurrent_executions', 'notes', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(name)
  - constraint: rate_limit_per_minute >= 1 and rate_limit_per_minute <= 6000
  - constraint: max_concurrent_executions >= 0 and max_concurrent_executions <= 100
- `allowed_command_sets.json` — Named allow-list policies defining which commands can be executed, plus execution restrictions (working directories, timeouts). (18 rows; fields: ['id', 'name', 'status', 'default_timeout_ms', 'max_timeout_ms', 'allow_any_working_dir', 'allowed_working_dirs', 'allow_powershell', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(name)
  - constraint: default_timeout_ms >= 1 and default_timeout_ms <= 300000
  - constraint: max_timeout_ms >= default_timeout_ms and max_timeout_ms <= 600000
  - constraint: allowed_working_dirs is non-null (may be empty array)
- `allowed_commands.json` — Concrete allow-listed commands available to execute_command and/or execute_powershell, optionally with argument restrictions. (18 rows; fields: ['id', 'allowed_command_set_id', 'command_name', 'command_type', 'status', 'argument_policy', 'argument_regex', 'description', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: fk(allowed_command_set_id) references allowed_command_sets(id) on delete cascade
  - constraint: unique(allowed_command_set_id, command_type, command_name)
  - constraint: if argument_policy = 'regex' then argument_regex is not null
  - constraint: if argument_policy in ('any','none') then argument_regex is null
- `tool_invocations.json` — Audit log of every MCP tool call (including read-only tools) with parameters, timing, and result metadata. (18 rows; fields: ['id', 'api_key_id', 'tool_name', 'request_params', 'status', 'started_at', 'ended_at', 'duration_ms', 'result_truncated', 'error_code', 'error_message', 'client_ip', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed', 'rejected']
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: duration_ms is null or (duration_ms >= 0 and duration_ms <= 600000)
  - constraint: if status in ('succeeded','failed','rejected') then ended_at is not null
  - constraint: if status in ('running','succeeded','failed') then started_at is not null
- `command_executions.json` — Detailed records for execute_command and execute_powershell runs, including validation decisions, exit codes, and captured output metadata. (20 rows; fields: ['id', 'invocation_id', 'api_key_id', 'execution_type', 'requested_command', 'requested_script', 'working_dir', 'timeout_ms', 'allowed_command_set_id', 'matched_allowed_command_id', 'status', 'pid', 'exit_code', 'stdout_bytes', 'stderr_bytes', 'stdout_preview', 'stderr_preview', 'started_at', 'ended_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'rejected', 'timed_out']
  - constraint: fk(invocation_id) references tool_invocations(id) on delete cascade
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: fk(allowed_command_set_id) references allowed_command_sets(id) on delete restrict
  - constraint: fk(matched_allowed_command_id) references allowed_commands(id) on delete set null

## Business rules enforced by the tools

- All tool calls must be associated with exactly one api_keys row; if api_keys.status != 'active' the request must be rejected and tool_invocations.status set to 'rejected' with error_code='KEY_REVOKED'.
- list_allowed_commands must return allowed_commands where allowed_command_set_id = api_keys.allowed_command_set_id and status='active'.
- execute_command must parse the provided parameters and store them in tool_invocations.request_params and command_executions.requested_command/working_dir/timeout_ms; execute_powershell must store tool_invocations.request_params and command_executions.requested_script/working_dir/timeout_ms.
- For execute_command/execute_powershell, the effective timeout_ms must be min(max(requested_timeout_ms or default_timeout_ms, 1), allowed_command_sets.max_timeout_ms) where the policy is api_keys.allowed_command_set_id at time of request.
- If allowed_command_sets.status != 'active' then any execute_command/execute_powershell must be rejected with command_executions.status='rejected' and tool_invocations.status='rejected'.
- If execute_powershell is called when allowed_command_sets.allow_powershell=false, the request must be rejected with error_code='POWERSHELL_DISABLED'.
- If allowed_command_sets.allow_any_working_dir=false and a workingDir is provided, it must match one of allowed_command_sets.allowed_working_dirs after normalization; otherwise reject with error_code='WORKDIR_NOT_ALLOWED'.
- An execution is allowed only if there exists an allowed_commands row with allowed_command_set_id matching the API key's policy, status='active', command_type matching the execution tool, and command_name matching the requested command (for cmd) or 'powershell' (for PowerShell wrapper). If none match, reject with error_code='NOT_ALLOWED'.
- If the matched allowed_commands.argument_policy='none', then execute_command must reject if the request contains additional arguments beyond the bare command_name; if 'regex', the raw command/script must match allowed_commands.argument_regex; otherwise reject with error_code='ARGS_NOT_ALLOWED'.
- Concurrency limit: at any moment, count(command_executions where api_key_id=? and status in ('queued','running')) must be <= api_keys.max_concurrent_executions; otherwise reject new executions with error_code='CONCURRENCY_LIMIT'.
- Rate limit: per api_key_id, the number of tool_invocations.created_at within the last rolling minute must be <= api_keys.rate_limit_per_minute; otherwise reject with error_code='RATE_LIMIT'.
- Read-only tools (list_running_processes, get_system_info, get_network_info, get_scheduled_tasks, get_service_info) must log tool_invocations with request_params containing the exact schema parameters: filter, detail, networkInterface, action, taskName, serviceName as applicable.
- For list_running_processes, when filter is provided it must be applied as a case-insensitive substring match against process name in the live OS query; the backend stores only the request and summary metadata, not the full process list.
- For get_system_info, detail must be either 'basic' or 'full' (default 'basic'); invalid values must result in tool_invocations.status='rejected' with error_code='VALIDATION_ERROR'.
- For get_network_info, when networkInterface is provided it must filter results to that interface name in the live OS query; invalid interface yields succeeded invocation with empty result or failed with error_code='NOT_FOUND' depending on implementation, but must be recorded.
- For get_scheduled_tasks and get_service_info, action defaults to 'query'; if action='status' and taskName/serviceName is missing, reject with error_code='VALIDATION_ERROR'.
- For command execution outputs, store stdout_bytes/stderr_bytes always; optionally store previews but truncate previews to a fixed maximum (e.g., 4096 chars) and set tool_invocations.result_truncated=true when truncation occurs.
- tool_invocations.status and command_executions.status must follow the declared transition graphs; direct transitions that skip states (e.g., received -> succeeded) are not permitted unless the service is explicitly implemented as synchronous and still writes started_at/ended_at consistently.