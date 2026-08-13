# Agentic Control Framework — local MCP environment

This backend stores workspaces and projects containing hierarchical tasks (tasks and subtasks), including dependencies, related file references, and an audit/activity trail. It also records AI-assisted operations (PRD parsing, task expansion, and task revision) and can generate derived artifacts like per-task Markdown files and a task table view.

Repository: https://github.com/FutureAtoms/agentic-control-framework
Homepage: https://smithery.ai/server/@FutureAtoms/agentic-control-framework

## Datastore

- `workspaces.json` — Top-level workspace configuration, primarily representing a filesystem directory that hosts one or more projects and their task artifacts. (12 rows; fields: ['id', 'workspace_path', 'status', 'active_project_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(workspace_path)
  - constraint: active_project_id references projects.id and projects.workspace_id must equal workspaces.id
  - constraint: workspace_path length between 1 and 4096
- `projects.json` — A task-manager project within a workspace, representing a coherent goal/initiative with tasks, AI operations, and generated artifacts. (12 rows; fields: ['id', 'workspace_id', 'name', 'description', 'status', 'next_task_seq', 'tasks_dir_path', 'task_table_md_path', 'last_task_files_generated_at', 'last_task_table_generated_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: foreign key(workspace_id) references workspaces.id on delete restrict
  - constraint: unique(workspace_id, name) where name is not null
  - constraint: next_task_seq >= 1
  - constraint: tasks_dir_path length between 1 and 4096
- `tasks.json` — Tasks and subtasks within a project. Supports hierarchical parent/child structure, dependencies, priority, related file paths, and status-based execution workflow. (33 rows; fields: ['id', 'project_id', 'display_id', 'parent_task_id', 'seq', 'title', 'description', 'priority', 'status', 'status_message_last', 'related_files', 'blocked_reason', 'error_detail', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['todo', 'inprogress', 'done', 'blocked', 'error']
  - constraint: foreign key(project_id) references projects.id on delete cascade
  - constraint: foreign key(parent_task_id) references tasks.id on delete cascade
  - constraint: parent_task_id must reference a task with parent_task_id is null (no subtask-of-subtask)
  - constraint: unique(project_id, display_id) where deleted_at is null
- `task_dependencies.json` — Directed dependency edges between tasks/subtasks within the same project. Used by getNextTask and validation when marking tasks done or in progress. (26 rows; fields: ['id', 'project_id', 'task_id', 'depends_on_task_id', 'created_at', 'updated_at'])
  - constraint: foreign key(project_id) references projects.id on delete cascade
  - constraint: foreign key(task_id) references tasks.id on delete cascade
  - constraint: foreign key(depends_on_task_id) references tasks.id on delete cascade
  - constraint: task_id != depends_on_task_id
- `activity_log.json` — Append-only log capturing user/tool actions, status changes, updates, AI operations (parsePrd/expandTask/reviseTasks), and artifact generation events. (36 rows; fields: ['id', 'workspace_id', 'project_id', 'task_id', 'event_type', 'message', 'payload', 'ai_provider', 'ai_model', 'ai_tokens_in', 'ai_tokens_out', 'ai_cost_usd', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['workspace_set', 'project_initialized', 'task_added', 'subtask_added', 'task_updated', 'task_removed', 'status_updated', 'context_viewed', 'task_files_generated', 'task_table_generated', 'prd_parsed', 'task_expanded', 'tasks_revised']
  - constraint: foreign key(workspace_id) references workspaces.id on delete cascade
  - constraint: project_id references projects.id on delete set null
  - constraint: task_id references tasks.id on delete set null
  - constraint: ai_tokens_in >= 0 when not null

## Business rules enforced by the tools

- setWorkspace(workspacePath) upserts workspaces.workspace_path (normalized) and sets status='active'; it creates an activity_log row with event_type='workspace_set' and payload.workspacePath.
- initProject(projectName?, projectDescription?) requires an active workspace; it creates a projects row with status='active', next_task_seq=1, tasks_dir_path derived from workspace_path; it updates workspaces.active_project_id to the new project; logs event_type='project_initialized'.
- All task operations (addTask, addSubtask, listTasks, updateStatus, getNextTask, updateTask, removeTask, getContext, generateTaskFiles, parsePrd, expandTask, reviseTasks, generateTaskTable) operate on workspaces.active_project_id; if none is set, the tools must fail with a validation error.
- addTask(title, description?, priority?, dependsOn?, relatedFiles?) creates a main task with parent_task_id=null, display_id = next_task_seq as string, seq=next_task_seq, and then increments projects.next_task_seq by 1 in the same transaction.
- addTask.priority defaults to 'medium' when omitted; addTask.relatedFiles is parsed from comma-separated string to tasks.related_files array; empty/blank entries are discarded.
- addTask.dependsOn is parsed as a comma-separated list of display IDs; for each, a task_dependencies edge is created from the new task to the prerequisite task; all prerequisite tasks must exist in the same project and must not be soft-deleted.
- addSubtask(parentId, title) requires parentId to reference an existing main task display_id in the active project; it creates a child task with parent_task_id set, display_id formatted as '<parentDisplayId>.<n>', seq = next sub-sequence under that parent.
- listTasks(status?, format?) returns only tasks with deleted_at is null; when status filter is present it filters by tasks.status; ordering is by main task seq then subtask seq; format only affects rendering, not stored data.
- updateStatus(id, newStatus, message?) resolves id as tasks.display_id in the active project; it enforces the status transition rules defined in tasks.lifecycle.transitions; it updates tasks.status and tasks.status_message_last=message (when provided) and appends activity_log(event_type='status_updated').
- A main task cannot be transitioned to 'done' if it has any non-deleted subtasks whose status != 'done'.
- getNextTask selects the highest priority actionable item: status in ('todo','inprogress') but prefer 'todo'; excludes tasks whose dependencies are not all status='done'; excludes tasks with status in ('blocked','error','done'); tie-breakers: priority high > medium > low, then seq ascending, then subtasks before next main task when parent is active.
- updateTask(id, title?, description?, priority?, relatedFiles?, message?) updates the referenced task; description and priority updates are only allowed when parent_task_id is null (main task). relatedFiles replaces tasks.related_files after parsing; logs event_type='task_updated' with message when provided.
- removeTask(id) performs a soft delete by setting deleted_at; if removing a main task, it soft-deletes its subtasks in the same transaction and deletes (or ignores via cascading/soft-delete logic) its dependency edges; logs event_type='task_removed'.
- getContext(id) returns the task, its parent (if subtask), its subtasks (if main task), its dependencies (incoming/outgoing), and recent activity_log rows for that task; logs event_type='context_viewed'.
- generateTaskFiles writes/updates Markdown artifacts on disk for all non-deleted tasks; it updates projects.last_task_files_generated_at and logs event_type='task_files_generated' with payload containing generated paths.
- generateTaskTable writes/updates a Markdown summary with checkboxes based on current statuses; it updates projects.last_task_table_generated_at and projects.task_table_md_path and logs event_type='task_table_generated'.
- parsePrd(filePath) records an activity_log row event_type='prd_parsed' with payload.filePath and AI metadata; it may create or replace tasks by inserting into tasks and task_dependencies, maintaining unique(project_id, display_id) and updating projects.next_task_seq accordingly.
- expandTask(taskId) resolves taskId as tasks.display_id; it overwrites existing subtasks by soft-deleting prior subtasks under that parent and creating new ones; logs event_type='task_expanded' with AI metadata.
- reviseTasks(fromTaskId, prompt) resolves fromTaskId as a main task display_id; it may modify tasks with seq >= fromTask.seq (and their subtasks) by updating titles/descriptions/priorities/dependencies; it logs event_type='tasks_revised' with payload.prompt and AI metadata.
- Dependency graph constraints are enforced on every write: prerequisites must exist, must be in same project, must not create cycles, and must not reference soft-deleted tasks.