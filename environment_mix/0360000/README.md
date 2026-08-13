# Todoist Task Manager — local MCP environment

This backend stores a synced representation of a user's Todoist workspace: projects, sections, tasks (including parent/child hierarchy), labels, and comments. The main workflows are CRUD + state transitions on tasks (create/update/complete/delete, bulk operations, hierarchy operations), plus management of projects/sections/labels and reading/creating comments. It also stores connection/test runs and lightweight performance telemetry for the MCP feature-test tools.

Repository: https://github.com/greirson/mcp-todoist
Homepage: https://smithery.ai/server/@greirson/mcp-todoist

## Datastore

- `todoist_connections.json` — Represents a configured Todoist account connection used by the MCP server (API token, sync metadata, and health). Used by connection and test tools; referenced by all domain entities for multi-tenant separation. (12 rows; fields: ['id', 'external_todoist_user_id', 'display_name', 'api_token_ciphertext', 'token_fingerprint', 'status', 'last_validated_at', 'last_error_code', 'last_error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'invalid_token', 'disabled']
  - constraint: unique(token_fingerprint)
  - constraint: api_token_ciphertext is encrypted at rest; never returned by read APIs
  - constraint: status in ('active','invalid_token','disabled')
- `todoist_containers.json` — Unified table for Todoist projects and sections (section belongs to a project). Supports listing and creation of projects/sections and resolving by name/id for task moves. (25 rows; fields: ['id', 'connection_id', 'type', 'external_id', 'name', 'parent_project_id', 'color', 'order_index', 'is_favorite', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: foreign key(connection_id) references todoist_connections(id) on delete cascade
  - constraint: if type='section' then parent_project_id is not null
  - constraint: if type='project' then parent_project_id is null
  - constraint: unique(connection_id, type, external_id) where external_id is not null
- `todoist_labels.json` — Todoist labels for a connection. Used for label CRUD, listing, and label usage statistics. Task<->label is modeled via todoist_task_labels join table. (35 rows; fields: ['id', 'connection_id', 'external_id', 'name', 'color', 'is_favorite', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key(connection_id) references todoist_connections(id) on delete cascade
  - constraint: unique(connection_id, lower(name)) where status <> 'deleted'
  - constraint: unique(connection_id, external_id) where external_id is not null
  - constraint: name length between 1 and 60
- `todoist_tasks.json` — Tasks and subtasks (modeled by parent_task_id). Supports create/get/update/delete/complete, bulk operations via filtering, hierarchy retrieval, subtask promotion/conversion, and label association (via embedded label_ids for quick reads plus join-table semantics enforced by constraints). (34 rows; fields: ['id', 'connection_id', 'external_id', 'content', 'description', 'project_container_id', 'section_container_id', 'parent_task_id', 'priority', 'due_date', 'due_timezone', 'due_string_raw', 'deadline_at', 'label_ids', 'status', 'completed_at', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'completed', 'deleted']
  - constraint: foreign key(connection_id) references todoist_connections(id) on delete cascade
  - constraint: unique(connection_id, external_id) where external_id is not null
  - constraint: content length between 1 and 500
  - constraint: priority in (1,2,3,4)
- `todoist_comments.json` — Comments attached to either a task or a project (Todoist supports both). Used by comment create/get tools. (35 rows; fields: ['id', 'connection_id', 'external_id', 'task_id', 'project_container_id', 'content', 'posted_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key(connection_id) references todoist_connections(id) on delete cascade
  - constraint: unique(connection_id, external_id) where external_id is not null
  - constraint: exactly one of (task_id, project_container_id) must be non-null
  - constraint: task_id must reference a task with same connection_id
- `todoist_tool_runs.json` — Operational telemetry and test execution records for todoist_test_connection, todoist_test_all_features, and todoist_test_performance. Stores per-tool timings, outcomes, and summarized assertions for diagnostics. (38 rows; fields: ['id', 'connection_id', 'tool_name', 'request_params', 'status', 'http_status', 'error_code', 'error_message', 'duration_ms', 'assertions', 'created_at', 'updated_at'])
  - lifecycle `status`: ['running', 'succeeded', 'failed']
  - constraint: foreign key(connection_id) references todoist_connections(id) on delete cascade
  - constraint: duration_ms >= 0 when not null
  - constraint: http_status between 100 and 599 when not null
  - constraint: if status in ('succeeded','failed') then duration_ms is not null

## Business rules enforced by the tools

- All reads/writes must be scoped by connection_id; cross-connection references are rejected.
- todoist_test_connection sets todoist_connections.status to 'active' on successful validation; to 'invalid_token' on auth failure; and updates last_validated_at and last_error_* accordingly.
- todoist_task_get supports lookup by exact external_id or internal id, and supports case-insensitive partial-name search over content; ambiguous partial-name matches must return a deterministic ordering (updated_at desc, then id) and either (a) return top N with a warning or (b) require disambiguation (implementation choice, but must be consistent).
- todoist_task_create requires content; optional attributes map to fields: description, due (due_date/due_string_raw/due_timezone), priority, label_ids, deadline_at, project_container_id, section_container_id, parent_task_id.
- todoist_task_update may target by id or partial-name search; it may update content, description, due fields, priority, label_ids, deadline_at, project_container_id, section_container_id, and parent_task_id, but must not allow updates when status='deleted'.
- todoist_task_complete transitions status from 'active' to 'completed' and sets completed_at; completing an already completed task is idempotent (no-op) but must not clear completed_at.
- todoist_task_delete transitions status to 'deleted' and sets deleted_at; deleting is idempotent but must not resurrect tasks.
- Bulk task tools (bulk_create/update/delete/complete) must execute atomically per request or provide per-item results; regardless, they must not partially apply silent failures.
- todoist_task_hierarchy_get returns a task plus all descendants (subtasks) ordered by created_at/order_index if available; tasks with status='deleted' are excluded unless explicitly requested by the implementation.
- todoist_subtask_create and todoist_subtasks_bulk_create require a valid parent_task_id whose status is not 'deleted'.
- todoist_task_convert_to_subtask sets parent_task_id for the target task; it must prevent cycles (a task cannot become a subtask of itself or any of its descendants).
- todoist_subtask_promote sets parent_task_id to null; the task remains in its project/section unless explicitly changed.
- todoist_project_get returns containers where type='project' and status<>'deleted'; todoist_section_get returns containers where type='section' filtered by parent_project_id (project).
- todoist_project_create inserts a container with type='project' and status='active'; todoist_section_create inserts a container with type='section' and a non-null parent_project_id referencing a project container.
- todoist_comment_create requires either a task target (by task id/name resolved to todoist_tasks.id) or a project target; it inserts todoist_comments with status='active'.
- todoist_comment_get filters comments by task_id or project_container_id; deleted comments are excluded by default.
- todoist_label_stats returns, per label, the count of tasks where label id is present in todoist_tasks.label_ids (or equivalently via join semantics) for status in ('active','completed').
- todoist_label_delete transitions status to 'deleted' and must also remove the label id from any task.label_ids during the same transaction (or schedule a compensating cleanup job; if scheduled, reads must not return deleted labels as attached).
- Performance and feature test tools must write a todoist_tool_runs row per invoked tool with duration_ms and status; failures must capture error_code/error_message without storing secrets.