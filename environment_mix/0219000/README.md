# Task Scheduler — local MCP environment

This backend stores scheduled tasks of different kinds (shell commands, HTTP API calls, AI prompts, and local reminder notifications) along with their schedules, enablement state, and run configuration. The scheduler creates execution records when tasks run (either on schedule or via manual trigger), tracks outcomes, and exposes history and server/runtime metadata for operational visibility.

Repository: https://github.com/daniellopez-2/scheduler-mcp
Homepage: https://smithery.ai/server/@daniellopez-2/scheduler-mcp

## Datastore

- `scheduler_tasks.json` — Primary table of scheduled tasks, regardless of type. Contains common fields (name, schedule, enabled, do_only_once) and type-specific configuration fields used by add_* and update_task tools. (38 rows; fields: ['id', 'task_type', 'name', 'description', 'schedule', 'enabled', 'do_only_once', 'status', 'command', 'api_url', 'api_method', 'api_headers', 'api_body', 'prompt', 'reminder_title', 'reminder_message', 'next_run_at', 'last_run_at', 'last_success_at', 'last_error_at', 'last_error_message', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'disabled', 'completed', 'deleted']
  - constraint: unique(name) WHERE status <> 'deleted'
  - constraint: enabled = true implies status = 'active'
  - constraint: status = 'disabled' implies enabled = false
  - constraint: status in ('completed','deleted') implies next_run_at IS NULL
- `task_executions.json` — Execution history for tasks. A row is created for every run attempt, whether scheduled or manually triggered, and updated as it progresses. (34 rows; fields: ['id', 'task_id', 'trigger_type', 'status', 'scheduled_for', 'started_at', 'finished_at', 'duration_ms', 'exit_code', 'stdout', 'stderr', 'http_status', 'http_response_headers', 'http_response_body', 'ai_output', 'error_message', 'error_details', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(task_id) references scheduler_tasks(id) on delete restrict (or require soft-delete)
  - constraint: duration_ms IS NULL OR duration_ms >= 0
  - constraint: http_status IS NULL OR (http_status >= 100 AND http_status <= 599)
  - constraint: exit_code IS NULL OR (exit_code >= 0 AND exit_code <= 255)
- `scheduler_locks.json` — Singleton-style coordination table to ensure only one active scheduler runner/leader performs due-task dispatch in multi-process deployments. (12 rows; fields: ['id', 'lock_name', 'owner_instance_id', 'acquired_at', 'renewed_at', 'lease_expires_at', 'created_at', 'updated_at'])
  - lifecycle `lock_name`: ['scheduler_dispatch']
  - constraint: unique(lock_name)
  - constraint: lease_expires_at >= acquired_at
  - constraint: renewed_at >= acquired_at
- `server_runtime.json` — Small metadata table used to serve get_server_info: build/runtime details, configuration flags, and last health timestamps. (12 rows; fields: ['id', 'instance_id', 'service_name', 'service_version', 'started_at', 'timezone', 'scheduler_tick_seconds', 'max_concurrent_executions', 'last_dispatch_at', 'created_at', 'updated_at'])
  - lifecycle `service_name`: ['Task Scheduler']
  - constraint: unique(instance_id)
  - constraint: scheduler_tick_seconds >= 1 AND scheduler_tick_seconds <= 3600
  - constraint: max_concurrent_executions >= 1 AND max_concurrent_executions <= 1000

## Business rules enforced by the tools

- list_tasks returns all scheduler_tasks where status <> 'deleted', ordered by created_at asc (or name asc), and includes type-specific fields as stored.
- get_task(task_id) must return the scheduler_tasks row by id where status <> 'deleted'; otherwise return not-found.
- add_command_task must create scheduler_tasks with task_type='command', set command, and must set enabled/do_only_once defaults to true when omitted; it must validate schedule before insert.
- add_api_task must create scheduler_tasks with task_type='api', set api_url, api_method default 'GET', api_headers/api_body nullable, and validate api_method is in allowed enum; validate schedule before insert.
- add_ai_task must create scheduler_tasks with task_type='ai', set prompt, and validate schedule before insert.
- add_reminder_task must create scheduler_tasks with task_type='reminder', store reminder_message from input.message and reminder_title from input.title, and validate schedule before insert.
- update_task(task_id, ...) must patch only provided non-null fields; it must not allow changing task_type implicitly, but may update the applicable config fields; it must validate schedule if schedule is changed.
- update_task must enforce type configuration consistency: e.g., for task_type='command', api_* and prompt and reminder_* must remain NULL (or be set to NULL) after update; attempts to set incompatible fields must be rejected.
- remove_task(task_id) must soft-delete by setting status='deleted', enabled=false, deleted_at=now(), next_run_at=NULL; it must not physically delete task rows if executions exist.
- enable_task(task_id) must set enabled=true and status='active' unless task is 'completed' or 'deleted' (reject). It must recompute next_run_at from schedule.
- disable_task(task_id) must set enabled=false and status='disabled' (unless already deleted), and set next_run_at=NULL.
- run_task_now(task_id) must create a task_executions row with trigger_type='manual', status='queued', scheduled_for=now(); it must reject if task status is 'deleted' or task enabled=false (or alternatively allow manual run but still record trigger_type='manual'—service must pick one policy and enforce it consistently).
- get_task_executions(task_id, limit) must return task_executions for the task ordered by created_at desc, with limit constrained to 1..100 (default 10).
- When a task execution transitions to 'running', started_at must be set; when it transitions to a terminal state (succeeded/failed/cancelled), finished_at and duration_ms must be set.
- If do_only_once=true and an execution reaches status='succeeded', the corresponding scheduler_tasks row must transition to status='completed', enabled=false, next_run_at=NULL.
- get_server_info must read the most recent server_runtime row for the current instance_id (or a singleton row), and must not require any task data.