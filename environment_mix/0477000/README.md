# Amazing Marvin MCP — local MCP environment

This backend stores Amazing Marvin productivity data for a single account: tasks (including hierarchy), categories/projects, labels, goals, and time tracking sessions. The main workflows are creating/organizing tasks and projects, completing tasks (with optional reward points), and tracking time against tasks with summaries for daily productivity and custom date ranges.

Repository: https://github.com/bgheneti/Amazing-Marvin-MCP
Homepage: https://smithery.ai/server/@bgheneti/amazing-marvin-mcp

## Datastore

- `accounts.json` — Amazing Marvin account connection and user-level settings used by all tools (credentials are managed outside DB; this stores metadata and sync state). (12 rows; fields: ['id', 'am_user_id', 'email', 'display_name', 'timezone', 'default_timezone_offset_minutes', 'status', 'last_successful_sync_at', 'last_error_code', 'last_error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'error']
  - constraint: unique(am_user_id)
  - constraint: default_timezone_offset_minutes between -840 and 840
- `categories.json` — Categories and projects (projects are categories with type='project'). Supports listing categories/projects and project overviews and hierarchy queries. (30 rows; fields: ['id', 'account_id', 'am_category_id', 'title', 'type', 'parent_category_id', 'color', 'archived', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(account_id, am_category_id)
  - constraint: parent_category_id must reference a row with same account_id
  - constraint: type in ('project','category')
  - constraint: archived=true implies status='archived'
- `tasks.json` — Tasks (and optionally sub-project items returned by child queries) with scheduling, completion, notes, and organization into project/category. Powers all task listing tools, create/complete, daily and overdue views, and project overview rollups. (35 rows; fields: ['id', 'account_id', 'am_item_id', 'title', 'note', 'project_id', 'category_id', 'parent_task_id', 'due_date', 'scheduled_for', 'priority', 'status', 'completed_at', 'completion_timezone_offset_minutes', 'reward_points_claimed', 'reward_points_claimed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'done', 'deleted']
  - constraint: unique(account_id, am_item_id)
  - constraint: title length between 1 and 500
  - constraint: completion_timezone_offset_minutes between -840 and 840
  - constraint: status='done' implies completed_at is not null
- `labels.json` — Labels/tags from Amazing Marvin and task-label assignments. Supports get_labels and label-aware organization in downstream clients (even if current tool surface does not filter by label). (25 rows; fields: ['id', 'account_id', 'am_label_id', 'name', 'color', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(account_id, am_label_id)
  - constraint: unique(account_id, name)
- `goals.json` — Goals from Amazing Marvin used for planning and reporting. Supports get_goals and can be used by clients for goal/task alignment. (12 rows; fields: ['id', 'account_id', 'am_goal_id', 'title', 'description', 'target_date', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'completed', 'archived', 'deleted']
  - constraint: unique(account_id, am_goal_id)
  - constraint: title length between 1 and 500
- `time_tracking.json` — Time tracking sessions for tasks, including currently running tracking. Supports start/stop, get_currently_tracked_item, get_time_tracks, and time_tracking_summary. (33 rows; fields: ['id', 'account_id', 'task_id', 'am_time_track_id', 'status', 'started_at', 'stopped_at', 'duration_seconds', 'note', 'created_at', 'updated_at'])
  - lifecycle `status`: ['running', 'stopped', 'deleted']
  - constraint: duration_seconds >= 0
  - constraint: stopped_at is null when status='running'
  - constraint: stopped_at is not null when status='stopped'
  - constraint: started_at <= stopped_at when stopped_at is not null

## Business rules enforced by the tools

- get_account_info reads from accounts by current authenticated account context and returns fields (am_user_id, email, display_name, timezone, status).
- test_api_connection must succeed only if an accounts row exists with status='active' and upstream credentials validate; on failure set accounts.status='error' and store last_error_code/message.
- get_projects returns categories where account_id matches and type='project' and status!='deleted'.
- get_categories returns categories where account_id matches and status!='deleted'.
- get_tasks returns tasks where account_id matches and status in ('active','done') (excluding deleted) with default ordering by due_date/scheduled_for/updated_at.
- get_all_tasks returns tasks where account_id matches and status='active' (excluding done/deleted).
- get_due_items returns tasks where account_id matches and status='active' and due_date is not null and due_date < now().
- get_daily_productivity_overview returns tasks for the account split into: overdue (due_date < today local), today_scheduled (scheduled_for within today local or due_date=today local), and optionally completed_today derived from completed_at with completion_timezone_offset_minutes.
- get_completed_tasks returns tasks where account_id matches and status='done' and completed_at >= now()-interval '7 days'.
- get_completed_tasks_for_date(date) returns tasks where account_id matches and status='done' and local_completed_date(date, completion_timezone_offset_minutes) equals the requested date.
- get_productivity_summary_for_time_range(start,end) aggregates tasks completed and time_tracking duration over the interval; requires start <= end and interval length <= 366 days.
- get_project_overview(project_id) requires project_id references categories.id with type='project' and same account_id; returns counts of active/done tasks and overdue tasks under that project.
- get_child_tasks(parent_id, recursive) treats parent_id as either tasks.id or categories.id; returns direct children by tasks.parent_task_id (for task parent) and categories.parent_category_id (for project/category parent). If recursive=true, returns all descendants with a hard cap of 5000 rows.
- create_task requires title and creates tasks row with status='active'; if project_id/category_id provided they must exist, match account_id, and not be deleted; due_date string inputs are normalized to datetime at 00:00:00 in account timezone.
- batch_create_tasks creates multiple tasks atomically up to 200 items per request; titles required; invalid foreign keys reject the whole batch.
- create_project creates a categories row with type='project' and status='active' and archived=false; title required; parent_category_id if provided must exist and match account.
- create_project_with_tasks creates a project (categories) plus child tasks assigned to that project in a single transaction; if any task invalid, no rows are created.
- mark_task_done(item_id, timezone_offset) requires item_id references tasks.id with same account and status!='deleted'; sets status='done', completed_at=now(), completion_timezone_offset_minutes=provided or account default; idempotent if already done (does not create additional completion events).
- batch_mark_done(task_ids) marks each referenced task done; maximum 200 ids; tasks not found or deleted cause partial failure reporting but must not mark unrelated tasks.
- claim_reward_points(task_id) requires tasks.status='done' and reward_points_claimed=false; sets reward_points_claimed=true and reward_points_claimed_at=now(); cannot be claimed twice.
- start_time_tracking(task_id) requires task exists, same account, status!='deleted'; if a running session exists for the account it must be stopped first (or tool returns a conflict); creates a time_tracking row status='running' started_at=now().
- stop_time_tracking(task_id) stops the currently running session for the account; if task_id is provided it must match the running session's task_id; sets status='stopped', stopped_at=now(), duration_seconds=round(extract(epoch from (stopped_at-started_at))).
- get_currently_tracked_item returns the single time_tracking row with status='running' for the account, joined to tasks.
- get_time_tracks returns time_tracking sessions for the account optionally filtered by task_id list; only status in ('running','stopped') are returned (excluding deleted).
- time_tracking_summary aggregates total duration_seconds grouped by task_id and day (local to account timezone) over a default interval (e.g., last 7 days) with a hard cap of 10,000 sessions scanned per request.