# ClickUp MCP Server — local MCP environment

This backend models a ClickUp-connected MCP server that mirrors a workspace hierarchy (workspace > space > folder > list) and supports CRUD + bulk operations on tasks, lists, and folders. The main workflows are: resolve entities by id or name within hierarchy scopes, mutate ClickUp objects (create/update/move/duplicate/delete), and keep a local cache plus an operation log for bulk/concurrent actions and auditability.

Repository: https://github.com/windalfin/clickup-mcp-server
Homepage: https://smithery.ai/server/@windalfin/clickup-mcp-server

## Datastore

- `workspaces.json` — Top-level ClickUp workspace cache used to answer hierarchy queries and to scope name-based lookups (space/folder/list/task). (12 rows; fields: ['id', 'clickup_workspace_id', 'name', 'status', 'hierarchy_snapshot', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(clickup_workspace_id)
  - constraint: name <> ''
  - constraint: created_at <= updated_at
- `nodes.json` — Unified hierarchy nodes representing ClickUp Spaces, Folders, and Lists. Enables resolving by (id) or (name within scope) and supports folder/list CRUD tools. (32 rows; fields: ['id', 'workspace_id', 'parent_node_id', 'node_type', 'clickup_node_id', 'name', 'content', 'archived', 'override_statuses', 'status', 'vendor_metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(workspace_id, clickup_node_id)
  - constraint: name <> ''
  - constraint: node_type in ('space','folder','list')
  - constraint: parent_node_id is null when node_type='space'
- `tasks.json` — Cached ClickUp tasks plus local fields required for filtering, moving, duplicating, and bulk updates. Supports id-based and name+list-based disambiguation. (34 rows; fields: ['id', 'workspace_id', 'list_node_id', 'clickup_task_id', 'name', 'description', 'status_value', 'priority', 'due_at', 'start_at', 'closed_at', 'assignee_clickup_user_ids', 'tags', 'time_estimate_ms', 'vendor_raw', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(workspace_id, clickup_task_id)
  - constraint: name <> ''
  - constraint: priority is null or (priority >= 1 and priority <= 4)
  - constraint: time_estimate_ms is null or time_estimate_ms >= 0
- `bulk_jobs.json` — Tracks bulk operations (create/update/move/delete) with batching and concurrency settings, plus per-item inputs and results. Used by create_bulk_tasks/update_bulk_tasks/move_bulk_tasks/delete_bulk_tasks tools. (30 rows; fields: ['id', 'workspace_id', 'job_type', 'target_list_node_id', 'batch_size', 'concurrency', 'input_items', 'result_summary', 'status', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'completed', 'failed', 'cancelled']
  - constraint: batch_size is null or (batch_size >= 1 and batch_size <= 500)
  - constraint: concurrency is null or (concurrency >= 1 and concurrency <= 50)
  - constraint: input_items length >= 1
  - constraint: If job_type in ('create_bulk_tasks','move_bulk_tasks') then target_list_node_id is not null
- `operation_log.json` — Immutable audit log for all tool calls and their ClickUp API interactions, including name-based resolution steps, warnings (e.g., status reset on move), and errors. Supports troubleshooting and ensures destructive operations are traceable. (39 rows; fields: ['id', 'workspace_id', 'tool_name', 'bulk_job_id', 'request_params', 'resolution_trace', 'clickup_request', 'clickup_response', 'http_status', 'warnings', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['success', 'error']
  - constraint: tool_name in ('get_workspace_hierarchy','create_task','get_task','get_tasks','update_task','move_task','duplicate_task','delete_task','create_bulk_tasks','update_bulk_tasks','move_bulk_tasks','delete_bulk_tasks','create_list','create_list_in_folder','get_list','update_list','delete_list','create_folder','get_folder','update_folder','delete_folder')
  - constraint: http_status is null or (http_status >= 100 and http_status <= 599)
  - constraint: created_at <= updated_at

## Business rules enforced by the tools

- Name-based resolution must be scope-aware: listName lookups are performed within a workspace and preferably within a specified parent (folder/space) if provided by the tool; if multiple matches remain, the tool must error with an ambiguity response.
- For get_task/update_task/move_task/duplicate_task/delete_task using taskName, the implementation must require enough scope to disambiguate: if taskName matches multiple active tasks across different lists and listName is not provided (or still ambiguous), the tool must error.
- create_task must reject requests that provide neither listId nor listName; if listName is used, it must resolve to exactly one active list node.
- get_tasks must reject requests that provide neither listId nor listName; resolved node must be of node_type='list'.
- update_task must reject requests that provide no update fields; only provided fields are mutated and reflected in tasks cache on success.
- move_task must require a destination list (listId or listName). When moving, tasks.list_node_id must update to the destination list; if the destination list has different status options, status_value may be set to null and a warning logged.
- duplicate_task creates a new task record with a new clickup_task_id and local id; it copies name/description/status_value/priority/dates/tags/assignees/time_estimate_ms/vendor_raw from the source unless ClickUp returns modified fields.
- delete_task and delete_list and delete_folder are permanent: upon successful vendor deletion, local status must transition to 'deleted' and must not transition back.
- delete_list must also mark all tasks with that list_node_id as status='deleted' after successful vendor deletion; delete_folder must mark all descendant lists and tasks as deleted after successful vendor deletion.
- create_list requires a space target: either spaceId or spaceName must resolve to a node_type='space' in the workspace; the created list node must have parent_node_id pointing to that space.
- create_list_in_folder requires folderId OR (folderName + (spaceId or spaceName)); when using folderName it must resolve uniquely within the specified space.
- get_folder/update_folder/delete_folder using folderName must require (spaceId or spaceName) and must resolve uniquely within that space.
- Bulk tools must create a bulk_jobs record and enforce batch_size in [1,500] and concurrency in [1,50] when provided; each input item must include the required identifier combination described by the tool docs.
- Bulk jobs must be executed with at-least-once semantics but written with idempotency at the item level: if an item references clickup_task_id that was already processed successfully for this bulk_jobs.id, it must not be applied twice; outcomes are recorded in bulk_jobs.result_summary and operation_log entries per batch or per item.