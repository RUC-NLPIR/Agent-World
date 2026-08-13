# Shell Server — local MCP environment

This backend supports a restricted shell-execution API by authenticating callers, enforcing per-key policies (allowed commands, directory sandboxing, timeouts), executing commands, and storing an auditable record of every invocation. Main workflows: a client presents an API key, submits a shell_execute request, the server validates policy/quota, runs the command, stores the execution + result, and exposes internal auditability/operational controls.

Repository: https://github.com/tumf/mcp-shell-server
Homepage: https://smithery.ai/server/mcp-shell-server

## Datastore

- `api_keys.json` — API keys used to authenticate callers and apply execution policy and quotas. (12 rows; fields: ['id', 'key_hash', 'name', 'status', 'allowed_commands', 'base_directory', 'max_timeout_seconds', 'requests_per_minute_limit', 'concurrent_exec_limit', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(name)
  - constraint: max_timeout_seconds >= 0 and max_timeout_seconds <= 3600
  - constraint: requests_per_minute_limit >= 1 and requests_per_minute_limit <= 6000
- `shell_executions.json` — One record per shell_execute invocation, including validated inputs, execution metadata, and lifecycle status. (34 rows; fields: ['id', 'api_key_id', 'requested_directory', 'resolved_directory', 'requested_timeout_seconds', 'effective_timeout_seconds', 'stdin', 'command_argv', 'command_name', 'status', 'rejection_reason', 'started_at', 'finished_at', 'duration_ms', 'exit_code', 'stdout_bytes', 'stderr_bytes', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'timed_out', 'rejected', 'cancelled']
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: command_argv length >= 1
  - constraint: requested_directory != ''
  - constraint: resolved_directory != ''
- `shell_execution_outputs.json` — Captured stdout/stderr and any structured metadata for an execution. Split out to avoid bloating the main execution table. (35 rows; fields: ['id', 'execution_id', 'stdout', 'stderr', 'stdout_truncated', 'stderr_truncated', 'max_capture_bytes', 'created_at', 'updated_at'])
  - lifecycle `status`: ['present']
  - constraint: fk(execution_id) references shell_executions(id) on delete cascade
  - constraint: unique(execution_id)
  - constraint: max_capture_bytes >= 0 and max_capture_bytes <= 10485760
- `rate_limit_counters.json` — Rolling counters used to enforce per-key rate limits for shell_execute. (23 rows; fields: ['id', 'api_key_id', 'window_start', 'window_seconds', 'request_count', 'rejected_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'sealed']
  - constraint: fk(api_key_id) references api_keys(id) on delete cascade
  - constraint: unique(api_key_id, window_start, window_seconds)
  - constraint: window_seconds in (1, 10, 60, 300, 900, 3600)
  - constraint: request_count >= 0

## Business rules enforced by the tools

- shell_execute must create a shell_executions row for every request, including requests that are rejected prior to running (status='rejected').
- shell_execute.command maps to shell_executions.command_argv and shell_executions.command_name (command_argv[0]); command_name must be one of: find, cat, ls, wc, pwd, grep, touch.
- shell_execute.directory maps to shell_executions.requested_directory and must resolve to shell_executions.resolved_directory; resolved_directory must be within api_keys.base_directory (path traversal blocked). Otherwise set status='rejected' and rejection_reason='directory_outside_base'.
- shell_execute.timeout (if provided) must be >= 0 and must not exceed api_keys.max_timeout_seconds; effective_timeout_seconds = min(requested_timeout_seconds or server_default, api_keys.max_timeout_seconds). If requested_timeout_seconds < 0 reject the request.
- shell_execute.stdin maps to shell_executions.stdin; server may enforce a maximum stdin size; if exceeded reject with rejection_reason='stdin_too_large'.
- If api_keys.status != 'active', shell_execute must be rejected (status='rejected') with rejection_reason='key_inactive'.
- Before transitioning an execution from queued->running, enforce api_keys.concurrent_exec_limit by counting running executions for that api_key_id; if limit exceeded reject with rejection_reason='concurrency_limited' or keep queued depending on implementation, but must not run.
- Enforce api_keys.requests_per_minute_limit using rate_limit_counters: increment request_count atomically per (api_key_id, window_start, window_seconds=60); if increment would exceed limit, record the execution as rejected with rejection_reason='rate_limited' and increment rejected_count.
- When a process starts, set shell_executions.started_at and status='running'. On completion set finished_at, duration_ms, exit_code, and terminal status: succeeded (exit_code=0), failed (exit_code!=0), timed_out (killed due to timeout), cancelled (operator/system cancel).
- For executed commands, store outputs in shell_execution_outputs (one row per execution). stdout_bytes/stderr_bytes in shell_executions must reflect the stored (possibly truncated) sizes, and stdout_truncated/stderr_truncated must be true when capture exceeded max_capture_bytes.
- Valid status transitions must match the lifecycle definitions; terminal states (succeeded/failed/timed_out/rejected/cancelled) are immutable.