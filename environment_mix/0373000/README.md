# Chain of Thought — local MCP environment

This backend stores projects, their task plans, and an auditable history of agent “thought” operations (plan/analyze/reflect/execute/verify) that create and update tasks. It supports task lifecycle management (split/list/query/detail/update/complete/delete/clear) with dependency tracking, plus project rule/spec initialization and controlled backup snapshots when clearing tasks.

Repository: https://github.com/liorfranko/mcp-chain-of-thought
Homepage: https://smithery.ai/server/@liorfranko/mcp-chain-of-thought

## Datastore

- `projects.json` — Top-level workspace for a user/repo integration. Holds project specification/rules and governs task lists and thought sessions. (12 rows; fields: ['id', 'name', 'repository_url', 'rules_spec', 'rules_version', 'rules_updated_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(repository_url) where repository_url is not null
  - constraint: rules_version >= 0
  - constraint: name <> ''
- `tasks.json` — Canonical task records with planning metadata, implementation/verification guidance, and completion reporting. Supports updates with restrictions after completion and provides data for list/query/detail tools. (31 rows; fields: ['id', 'project_id', 'name', 'description', 'notes', 'priority', 'status', 'implementation_guide', 'verification_criteria', 'related_files', 'summary', 'completion_report', 'completed_at', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['planned', 'ready', 'in_progress', 'blocked', 'completed', 'cancelled']
  - constraint: unique(project_id, name) where deleted_at is null
  - constraint: priority between 1 and 5
  - constraint: name <> ''
  - constraint: completed_at is not null iff status = 'completed'
- `task_dependencies.json` — Directed dependency graph between tasks within a project. Enables split_tasks to define dependencies and complete_task to update readiness of dependents. (34 rows; fields: ['id', 'project_id', 'task_id', 'depends_on_task_id', 'dependency_type', 'created_at', 'updated_at'])
  - lifecycle `dependency_type`: ['blocks', 'requires_context', 'optional']
  - constraint: unique(task_id, depends_on_task_id)
  - constraint: task_id <> depends_on_task_id
  - constraint: task_id and depends_on_task_id must belong to same project_id
  - constraint: no cyclic dependencies per project (enforced at write time)
- `thought_sessions.json` — Auditable chain-of-thought sessions that group tool invocations (plan/analyze/reflect/process_thought/execute/verify) and store high-level reasoning artifacts without requiring tool parameters. (16 rows; fields: ['id', 'project_id', 'root_task_id', 'mode', 'status', 'summary', 'next_thought_needed', 'created_at', 'updated_at', 'closed_at'])
  - lifecycle `status`: ['open', 'closed', 'failed']
  - constraint: next_thought_needed = false implies status in ('closed','failed') OR explicitly allowed while open (set by tool)
  - constraint: mode is required
  - constraint: root_task_id must belong to project_id when not null
- `task_backups.json` — Snapshot backups of a project's task state before destructive operations (clear_all_tasks, split_tasks with clearAllTasks/overwrite modes). Enables integrity and potential restore workflows. (12 rows; fields: ['id', 'project_id', 'reason', 'status', 'snapshot', 'retention_expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['created', 'expired']
  - constraint: reason is required
  - constraint: snapshot must include tasks and dependencies arrays
  - constraint: at most 20 backups per project with status='created' (quota)

## Business rules enforced by the tools

- All tools operate within exactly one projects row; if none exists for the configured repo/workspace, one is created in status='active'.
- plan_task creates a thought_sessions row with mode='plan_task' and status='open', then writes a summary and closes it when done.
- analyze_task and reflect_task append a thought_sessions row (mode accordingly) and store only high-level artifacts in summary; no task mutation is required but is allowed via subsequent tools.
- split_tasks must create/update tasks and task_dependencies for a project. It must support update modes by mutating tasks as follows: append = only insert new tasks; overwrite = soft-delete all unfinished tasks then insert/replace; selective = match by (project_id, name) to update existing unfinished tasks and insert missing; clearAllTasks = create a task_backups snapshot then soft-delete all unfinished tasks and dependencies, then insert the new plan.
- list_tasks returns all tasks where project_id matches and deleted_at is null, including derived dependency counts from task_dependencies.
- query_task searches tasks by keyword across name/description/notes and by exact id, restricted to project_id and deleted_at is null.
- get_task_detail returns the full tasks row plus dependency edges (both incoming/outgoing) from task_dependencies for the same project.
- execute_task may transition a task status from ready/blocked/planned to in_progress only if all 'blocks' dependencies are completed; otherwise it must set status='blocked'.
- verify_task may be run for any non-deleted task; it records its outcome in a thought_sessions row (mode='verify_task') and must not set status='completed' directly.
- complete_task can set status='completed' only if the task is not deleted and not already completed, and if all 'blocks' dependencies are completed; it must set completed_at and write completion_report, then update dependents: any dependent task with all blockers completed may transition from planned/blocked to ready.
- delete_task is only allowed when tasks.status in ('planned','ready','in_progress','blocked','cancelled') and deleted_at is null; it must refuse deletion when status='completed'.
- clear_all_tasks must create a task_backups snapshot then soft-delete all tasks where status <> 'completed' by setting deleted_at, and delete (or soft-delete) task_dependencies involving deleted tasks.
- update_task: if status='completed', only summary and related_files may be changed; otherwise name/description/notes/priority/implementation_guide/verification_criteria/related_files and dependency edges may be updated subject to constraints (no cycles, same project).
- init_project_rules must upsert projects.rules_spec, increment rules_version by 1, set rules_updated_at, and create a thought_sessions row with mode='init_project_rules'.
- FK integrity: task_dependencies.task_id and depends_on_task_id must reference existing tasks with deleted_at is null at time of creation; when a task is soft-deleted, dependent edges must be removed or marked invalid in the same transaction.
- Uniqueness: within a project, active (non-deleted) task names must be unique to support selective matching in split_tasks.
- Quota/limits: a project may have at most 500 non-deleted tasks; a single task may have at most 50 dependencies; related_files array length must be <= 200.