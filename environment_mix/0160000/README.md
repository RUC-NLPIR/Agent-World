# Hevy Fitness API MCP Server — local MCP environment

This backend stores a Hevy user's workout history (workouts, exercises, sets) plus reusable planning artifacts (routines, routine folders, and exercise templates). Primary workflows are: listing/counting workouts, creating/updating workouts, syncing changes via workout events, and managing routines/folders/templates for building workouts.

Repository: https://github.com/chrisdoc/hevy-mcp
Homepage: https://smithery.ai/server/@chrisdoc/hevy-mcp

## Datastore

- `accounts.json` — Hevy account scope for all user-owned data. Represents the authenticated user/account the MCP server is operating on, plus API credential metadata and basic quota/rate-limiting counters. (12 rows; fields: ['id', 'hevy_user_id', 'display_name', 'api_token_hash', 'status', 'daily_request_limit', 'daily_request_count', 'daily_count_reset_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'suspended']
  - constraint: unique(hevy_user_id)
  - constraint: daily_request_limit >= 0
  - constraint: daily_request_count >= 0
  - constraint: daily_request_count <= daily_request_limit OR daily_request_limit = 0
- `workouts.json` — Logged workouts. Stores workout header info and embeds performed exercise/sets as structured JSON to keep collection count low while preserving fidelity needed for create/update/read tools. (19 rows; fields: ['id', 'account_id', 'hevy_workout_id', 'title', 'description', 'privacy', 'started_at', 'ended_at', 'duration_seconds', 'exercises', 'source', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(account_id, hevy_workout_id)
  - constraint: title <> ''
  - constraint: ended_at >= started_at
  - constraint: duration_seconds = EXTRACT(EPOCH FROM (ended_at - started_at))
- `workout_events.json` — Append-only event log of workout changes (updates/deletes) used for incremental sync (get-workout-events). (18 rows; fields: ['id', 'account_id', 'workout_id', 'hevy_workout_id', 'event_type', 'effective_at', 'payload_snapshot', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['created', 'updated', 'deleted']
  - constraint: index(account_id, effective_at DESC)
  - constraint: index(account_id, hevy_workout_id, effective_at DESC)
  - constraint: effective_at <= now() + interval '5 minutes'
  - constraint: event_type IN ('created','updated','deleted')
- `routines.json` — Workout routines (templates) used for planning. Stores exercise configurations as structured JSON. Folder assignment is allowed at creation time, but cannot be changed via update-routine tool, so folder_id is treated as immutable after creation in service rules. (20 rows; fields: ['id', 'account_id', 'hevy_routine_id', 'title', 'notes', 'folder_id', 'is_default', 'exercise_configs', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(account_id, hevy_routine_id)
  - constraint: title <> ''
  - constraint: json_array_length(exercise_configs) >= 1
  - constraint: folder_id IS NULL OR exists(select 1 from routine_folders f where f.id = folder_id and f.account_id = routines.account_id)
- `routine_folders.json` — Folders used to organize routines. Maintains a stable ordering via index position. Creating a folder inserts at index 0 and shifts other folders. (18 rows; fields: ['id', 'account_id', 'hevy_folder_id', 'title', 'index', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(account_id, hevy_folder_id)
  - constraint: unique(account_id, index) WHERE status='active'
  - constraint: index >= 0
  - constraint: title <> ''
- `exercise_templates.json` — Catalog of exercise templates available to the account (default + custom). Referenced by workouts and routines when possible. (18 rows; fields: ['id', 'account_id', 'hevy_exercise_template_id', 'title', 'type', 'primary_muscle_group', 'secondary_muscle_groups', 'is_default', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(account_id, hevy_exercise_template_id)
  - constraint: title <> ''
  - constraint: json_array_length(secondary_muscle_groups) >= 0

## Business rules enforced by the tools

- All read tools (get-workouts/get-workout/get-routines/get-routine/get-exercise-templates/get-exercise-template/get-routine-folders/get-routine-folder) must scope results by account_id and order lists from newest to oldest using the upstream created/started timestamps when available (fallback: created_at).
- get-workout-count returns count(*) from workouts where account_id = ? and status = 'active'.
- create-workout must reject if title is empty, started_at or ended_at missing, ended_at < started_at, or exercises array is missing/empty, or any exercise has zero sets.
- update-workout must locate by (account_id, hevy_workout_id) and only update allowed fields: title, description, started_at, ended_at, privacy, exercises; it must write a workout_events row with event_type='updated' and effective_at=now().
- When a workout is deleted upstream (or via sync), the system must set workouts.status='deleted' (no hard delete) and append workout_events(event_type='deleted').
- get-workout-events must return events where account_id=? and effective_at >= since_date (tool input), ordered by effective_at desc, and be paginatable (cursor/limit handled at query layer).
- create-routine must reject if title is empty or exercise_configs is empty, and if folder_id is provided it must reference a routine_folders row with matching account_id and status='active'.
- update-routine must not allow changing folder_id; attempts to change it must be ignored or rejected. It may update title, notes, and exercise_configs only.
- create-routine-folder must insert the new folder at index=0 and atomically increment index by 1 for all other active folders for that account to maintain unique(account_id,index).
- get-exercise-templates must enforce a maximum page size of 100 at the query layer; if a higher limit is requested it must be clamped to 100.
- Foreign key integrity: routines.folder_id cannot reference a folder belonging to another account; workout_events.workout_id (if present) must reference a workout belonging to the same account.
- Quota enforcement: if accounts.daily_request_limit > 0 and daily_request_count >= daily_request_limit, mutating tools (create/update) must be rejected; read tools may be allowed or also rejected depending on policy, but must at least increment daily_request_count consistently.