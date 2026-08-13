# GitLab Merge Request Integration — local MCP environment

This backend stores a local, queryable mirror of GitLab projects, merge requests, issues, diffs, and discussion notes to support an integration that can list and fetch MR/issue data and create/update MR comments and metadata. The main workflow is: sync or lazy-fetch GitLab entities into local tables, serve read tools from the mirror, and persist outbound mutations (new notes, title/description updates) with status tracking and eventual consistency back to GitLab.

Repository: https://github.com/kopfrechner/gitlab-mr-mcp
Homepage: https://smithery.ai/server/@kopfrechner/gitlab-mr-mcp

## Datastore

- `gitlab_connections.json` — Represents an authenticated GitLab connection (instance + access token) used by the integration to read/write GitLab resources. Also used for rate-limiting and audit of tool calls. (12 rows; fields: ['id', 'gitlab_base_url', 'access_token_hash', 'token_last4', 'default_project_id', 'status', 'last_successful_sync_at', 'last_error', 'rate_limit_bucket', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(gitlab_base_url, access_token_hash)
  - constraint: gitlab_base_url must match ^https?://
  - constraint: token_last4 length = 4 when not null
- `projects.json` — Mirrored GitLab projects available to the connection; used by get_projects and as the parent for issues and merge requests. (20 rows; fields: ['id', 'connection_id', 'gitlab_project_id', 'path_with_namespace', 'name', 'web_url', 'default_branch', 'visibility', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'inaccessible']
  - constraint: unique(connection_id, gitlab_project_id)
  - constraint: unique(connection_id, path_with_namespace)
  - constraint: gitlab_project_id > 0
- `merge_requests.json` — Mirrored GitLab merge requests for a project; supports listing open MRs and updating title/description. (33 rows; fields: ['id', 'project_id', 'gitlab_mr_iid', 'gitlab_mr_id', 'title', 'description', 'source_branch', 'target_branch', 'web_url', 'author_username', 'state', 'draft', 'last_synced_at', 'last_diff_synced_at', 'updated_in_gitlab_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'syncing', 'error']
  - constraint: unique(project_id, gitlab_mr_iid)
  - constraint: gitlab_mr_iid > 0
  - constraint: length(title) between 1 and 255
  - constraint: source_branch <> target_branch
- `merge_request_diffs.json` — Stores per-file diffs for a merge request (current and historical snapshots) to support get_merge_request_diff and anchoring diff comments to a file/line. (39 rows; fields: ['id', 'merge_request_id', 'diff_ref_base_sha', 'diff_ref_head_sha', 'diff_ref_start_sha', 'old_path', 'new_path', 'a_mode', 'b_mode', 'new_file', 'renamed_file', 'deleted_file', 'diff', 'is_current', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded', 'error']
  - constraint: At most one row per (merge_request_id) where is_current = true
  - constraint: old_path and new_path length between 1 and 1024
- `notes.json` — Stores merge request notes (general comments) and diff/line notes (positioned discussions) mirrored from GitLab and created by this integration. (33 rows; fields: ['id', 'merge_request_id', 'project_id', 'gitlab_note_id', 'discussion_id', 'note_type', 'body', 'author_username', 'system', 'resolved', 'position', 'diff_file_id', 'line_code', 'status', 'gitlab_created_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['synced', 'pending_create', 'failed', 'deleted']
  - constraint: gitlab_note_id > 0 when not null
  - constraint: length(body) between 1 and 100000
  - constraint: note_type = 'diff' implies position is not null
  - constraint: note_type = 'general' implies position is null

## Business rules enforced by the tools

- Tools operate within exactly one gitlab_connections row; if multiple connections exist, the active one is selected, otherwise calls fail with a configuration error.
- For tools with empty parameter schemas, the implementation must derive the target project (and merge request/issue context where needed) from gitlab_connections.default_project_id and/or the most recently accessed merge_requests row for that connection (tracked outside this schema or via updated_at ordering).
- get_projects returns projects where connection_id matches the active connection and status != 'inaccessible'.
- list_open_merge_requests returns merge_requests for the default project where state = 'opened'.
- get_merge_request_details returns the merge_requests row for the current/default MR context; if local status is 'stale' or last_synced_at is older than a configured TTL, the backend must refresh from GitLab and transition status to syncing->active or syncing->error.
- get_merge_request_comments returns notes for the target merge_request_id ordered by gitlab_created_at asc (fallback created_at), including both note_type = 'general' and note_type = 'diff'.
- add_merge_request_comment inserts a notes row with note_type='general', status='pending_create', then attempts GitLab creation; on success sets status='synced' and fills gitlab_note_id/gitlab_created_at; on failure sets status='failed' and stores the error in an application log.
- add_merge_request_diff_comment inserts a notes row with note_type='diff', status='pending_create', requiring position (and/or line_code) that references merge_request_diffs diff_ref_* shas; if the diff snapshot is not current, the call must refresh diffs before posting.
- get_merge_request_diff returns merge_request_diffs where merge_request_id matches and is_current=true; if none exist or last_diff_synced_at is stale, refresh diffs from GitLab and mark previous rows status='superseded' and is_current=false before inserting new active/current rows.
- set_merge_request_title updates merge_requests.title locally and performs a GitLab update; if GitLab update fails, status transitions to error and the local title must be reverted or marked stale requiring resync (implementation choice must be consistent).
- set_merge_request_description updates merge_requests.description locally and performs a GitLab update with the same consistency rules as title updates.
- get_issue_details must be served from a mirrored issues store; because issues are not modeled as a standalone collection here, the implementation must fetch directly from GitLab on demand and optionally cache into projects metadata or an external cache; if persistent storage is required, add an issues collection mirroring GitLab issue fields (project_id, gitlab_issue_iid, title, description, state, web_url, labels).
- Foreign key integrity: merge_requests.project_id must reference an existing projects row for the same connection; notes.project_id must match merge_requests.project_id when merge_request_id is set.
- Quota/rate limiting: per gitlab_connections row, the backend must throttle GitLab API calls to a configured maximum requests/minute; when exceeded, tool calls return a retryable error and do not mutate local state except for updated_at on the connection.