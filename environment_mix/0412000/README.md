# Dart — local MCP environment

Dart stores collaborative work artifacts—tasks and docs—organized into dartboards and folders, with assignment, tagging, and lifecycle management (active vs trashed). The main workflows are listing/searching tasks and docs, creating/updating them, and soft-deleting (trashing) items while retaining recoverability and audit history.

Repository: https://github.com/its-dart/dart-mcp-server
Homepage: https://smithery.ai/server/@its-dart/dart-mcp-server

## Datastore

- `workspaces.json` — Tenant/workspace container for all Dart data. Used for scoping list/search operations and configuration returned by get_config. (18 rows; fields: ['id', 'slug', 'name', 'default_timezone', 'status', 'settings', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(slug)
  - constraint: default_timezone != ''
  - constraint: settings is a JSON object
  - constraint: status in ('active','suspended','deleted')
- `users.json` — Workspace users used for task assignees and authorship metadata. Minimal profile plus membership role per workspace. (18 rows; fields: ['id', 'workspace_id', 'email', 'display_name', 'role', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'invited', 'deactivated']
  - constraint: unique(workspace_id, email)
  - constraint: email contains '@'
  - constraint: role in ('owner','admin','member','viewer')
  - constraint: status in ('active','invited','deactivated')
- `tasks.json` — Task objects with lifecycle, scheduling fields, dartboard grouping, and soft-delete (trash). Supports list_tasks, create_task, get_task, update_task, delete_task. (20 rows; fields: ['id', 'workspace_id', 'dartboard_id', 'parent_task_id', 'title', 'description', 'status', 'priority', 'size', 'start_at', 'due_at', 'completed_at', 'assignee_ids', 'tag_names', 'is_trashed', 'trashed_at', 'created_by_user_id', 'updated_by_user_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['backlog', 'todo', 'in_progress', 'blocked', 'done', 'cancelled']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: fk(parent_task_id) references tasks(id) on delete set null
  - constraint: fk(created_by_user_id) references users(id) on delete set null
  - constraint: fk(updated_by_user_id) references users(id) on delete set null
- `docs.json` — Document objects with folder organization and soft-delete (trash). Supports list_docs, create_doc, get_doc, update_doc, delete_doc. (18 rows; fields: ['id', 'workspace_id', 'folder_id', 'title', 'content_text', 'content_plaintext', 'status', 'is_trashed', 'trashed_at', 'created_by_user_id', 'updated_by_user_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'published', 'archived']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: fk(created_by_user_id) references users(id) on delete set null
  - constraint: fk(updated_by_user_id) references users(id) on delete set null
  - constraint: title != ''
- `api_keys.json` — API credentials and request-scoped configuration used by get_config and to authorize/attribute calls to list/create/get/update/delete tools. (18 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'scopes', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: scopes is an array of unique strings

## Business rules enforced by the tools

- All tool calls must be authorized by an active api_keys record; revoked keys are rejected.
- All reads/writes are scoped to api_keys.workspace_id; cross-workspace access is forbidden even if an object id is known.
- delete_task and delete_doc must be soft deletes: set is_trashed=true and trashed_at=now; they must not modify other fields besides updated_at/updated_by_user_id.
- get_task/get_doc must return 404 if the item does not exist in the caller workspace; by default trashed items are excluded unless an internal flag is used (not exposed in tool surface).
- update_task/update_doc must not allow updates to trashed items unless first restored (restore not exposed in tool surface); attempts are rejected.
- Task status transitions must follow tasks.lifecycle.transitions; when transitioning to done, completed_at is set to now; when transitioning away from done, completed_at is cleared.
- Task assignee_ids must reference existing active users in the same workspace; duplicates are rejected.
- Task parent_task_id must reference a task in the same workspace and must not create cycles (enforced via recursive check).
- Task due_at must be >= start_at when both are present; invalid ranges are rejected.
- Doc content_plaintext must be derived from content_text on create/update (server-side); clients cannot set it inconsistently.
- list_tasks filtering is implemented via indexes on (workspace_id, status, priority, due_at, dartboard_id) plus GIN-like indexes on assignee_ids and tag_names; list_docs filtering uses (workspace_id, folder_id, title) and full-text index on content_plaintext.
- get_config returns workspace settings plus derived capabilities based on api_key.scopes (e.g., writable=false if no *:write scope).