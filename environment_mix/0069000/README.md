# GitHub — local MCP environment

This backend stores a cached/normalized view of GitHub entities (users, repositories, git refs/files, issues, pull requests, and comments/reviews) plus an audit trail of tool calls performed by an authenticated GitHub installation. Primary workflows: repository/file operations (create/update/push/list commits/branches), issue & PR lifecycle management (create/update/comment/review/merge), and cross-entity search (repos/code/issues/users) over indexed snapshots.

Repository: https://github.com/dev-assistant-ai/mcp-servers
Homepage: https://smithery.ai/server/@dev-assistant-ai/github

## Datastore

- `github_connections.json` — Represents an authenticated GitHub connection (OAuth token or GitHub App installation) used to execute tool calls and scope access to cached resources. (18 rows; fields: ['id', 'provider', 'github_account_id', 'github_login', 'account_type', 'scopes', 'token_ciphertext', 'installation_id', 'status', 'last_verified_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'error']
  - constraint: unique(provider, github_account_id, installation_id)
  - constraint: github_account_id > 0
  - constraint: installation_id is null OR installation_id > 0
  - constraint: status in ('active','revoked','error')
- `github_repositories.json` — Cached repository metadata plus lightweight git state needed for branch/file/commit operations and search results. (19 rows; fields: ['id', 'connection_id', 'github_repo_id', 'owner_login', 'name', 'full_name', 'visibility', 'default_branch', 'description', 'homepage', 'is_fork', 'forked_from_repo_id', 'archived', 'disabled', 'status', 'pushed_at', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'pending_fork', 'deleted', 'access_revoked']
  - constraint: unique(connection_id, github_repo_id)
  - constraint: unique(full_name)
  - constraint: github_repo_id > 0
  - constraint: default_branch <> ''
- `github_git_objects.json` — Git-layer objects for repositories: branches/refs, commits, and file blobs/trees required to implement file operations, listing commits, PR file diffs, and code search indexing. (18 rows; fields: ['id', 'repo_id', 'object_type', 'ref_name', 'branch_name', 'sha', 'parent_sha_list', 'author_login', 'author_email', 'message', 'committed_at', 'path', 'encoding', 'content_text', 'content_bytes_b64', 'size_bytes', 'status', 'last_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['present', 'stale', 'tombstoned']
  - constraint: sha ~ '^[0-9a-f]{7,40}$'
  - constraint: unique(repo_id, object_type, sha, path, ref_name)
  - constraint: object_type='ref' implies ref_name is not null
  - constraint: object_type='ref' implies branch_name is null OR branch_name <> ''
- `github_issues_pull_requests.json` — Unified table for Issues and Pull Requests (PRs are issues with extra PR fields). Supports create/update/list/get/search across issues and PRs. (18 rows; fields: ['id', 'repo_id', 'github_issue_id', 'number', 'kind', 'title', 'body', 'author_login', 'labels', 'assignees', 'milestone_number', 'state', 'locked', 'closed_at', 'is_draft', 'base_branch', 'head_branch', 'head_repo_full_name', 'mergeable_state', 'merged', 'merged_at', 'merged_by_login', 'status', 'github_updated_at', 'created_at', 'updated_at'])
  - lifecycle `state`: ['open', 'closed']
  - constraint: unique(repo_id, number)
  - constraint: unique(repo_id, github_issue_id)
  - constraint: number > 0
  - constraint: github_issue_id > 0
- `github_discussion_artifacts.json` — Stores comments, review comments, review submissions, review threads, and status-check rollups needed for issue/PR commenting, reviewing, resolving conversations, and retrieving PR status/files/comments/reviews. (18 rows; fields: ['id', 'repo_id', 'issue_pr_id', 'artifact_type', 'github_id', 'author_login', 'body', 'in_reply_to_github_id', 'path', 'position', 'line', 'side', 'commit_sha', 'diff_hunk', 'review_state', 'thread_resolved', 'file_status', 'additions', 'deletions', 'changes', 'status_rollup', 'status', 'github_created_at', 'github_updated_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'edited', 'resolved', 'deleted']
  - constraint: artifact_type in ('issue_comment','pr_issue_comment','pr_review','pr_review_comment','pr_review_thread','pr_changed_file','pr_combined_status')
  - constraint: unique(issue_pr_id, artifact_type, github_id) WHERE github_id is not null
  - constraint: line is null OR line > 0
  - constraint: position is null OR position > 0
- `github_tool_calls.json` — Immutable audit log of tool invocations, used for debugging, rate-limit/quota enforcement, and replay. Stores request/response metadata for each of the 32 tools. (23 rows; fields: ['id', 'connection_id', 'tool_name', 'request_json', 'resolved_repo_full_name', 'repo_id', 'issue_pr_id', 'http_status', 'rate_limit_remaining', 'rate_limit_reset_at', 'status', 'error_code', 'error_message', 'response_json', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: http_status is null OR (http_status >= 100 AND http_status <= 599)
  - constraint: rate_limit_remaining is null OR rate_limit_remaining >= 0
  - constraint: finished_at is null OR started_at is not null
  - constraint: finished_at is null OR finished_at >= started_at

## Business rules enforced by the tools

- Every tool invocation MUST insert a github_tool_calls row with tool_name and request_json before contacting GitHub, then transition status queued->running and finally to succeeded/failed with http_status and response_json/error fields populated.
- create_repository MUST create (or upsert) a github_repositories row with unique(full_name) and set status=active if GitHub returns success; if repository creation fails, no active repo row may be created unless GitHub indicates it already exists and caller has access.
- fork_repository MUST set target repo status=pending_fork until GitHub reports the fork is ready; transition pending_fork->active only after default_branch and github_repo_id are known.
- create_branch MUST upsert a github_git_objects row of object_type=ref with ref_name='refs/heads/{branch}' and sha set to the base commit; ref_name must be unique per repo.
- list_commits MUST read from github_git_objects where object_type=commit and repo_id matches; if cache miss or stale, it must fetch from GitHub and upsert commits with committed_at/message/author fields.
- get_file_contents MUST read from github_git_objects where object_type in ('blob','tree') and path matches; for directories it should return tree entries (stored as object_type=tree with path prefix) and for files return blob content fields. Content stored must obey size_bytes <= 10MB.
- create_or_update_file and push_files MUST create or update blob objects (object_type=blob) for each path, then create a commit object with parent_sha_list and message, and finally advance the target branch ref sha to the new commit sha in the ref record.
- create_issue MUST insert a github_issues_pull_requests row with kind='issue', state='open', and unique(repo_id, number) enforced from GitHub response; add_issue_comment MUST insert a github_discussion_artifacts row with artifact_type='issue_comment'.
- update_issue MUST only allow state transitions open<->closed and must set closed_at when transitioning to closed; it may not set merged-related fields.
- create_pull_request MUST insert a github_issues_pull_requests row with kind='pull_request', base_branch and head_branch required, and state='open'.
- merge_pull_request MUST only succeed if kind='pull_request' and state='closed' after merge; it MUST set merged=true and merged_at on success and must never set merged=true while state='open'.
- update_pull_request_branch MUST only be allowed for kind='pull_request' and must update the PR head ref sha and insert a new commit record when GitHub reports an update.
- create_pull_request_review MUST insert a github_discussion_artifacts row with artifact_type='pr_review' and review_state in the allowed enum; get_pull_request_reviews reads those rows.
- add_pull_request_comment MUST create artifact_type='pr_review_comment' with path and (line or position) present; reply_to_pull_request_comment MUST set in_reply_to_github_id and enforce the replied-to comment exists for the same issue_pr_id.
- resolve_pull_request_conversation MUST only apply to artifact_type='pr_review_thread' and set thread_resolved=true and status='resolved'; transitions to resolved must respect the lifecycle transitions defined.
- get_pull_request_files MUST read/write artifact_type='pr_changed_file' rows keyed by (issue_pr_id, path) and update additions/deletions/changes/file_status.
- get_pull_request_status MUST read/write a single artifact_type='pr_combined_status' per issue_pr_id; status_rollup must be valid JSON and reflect latest fetched state.
- search_repositories/search_code/search_issues/search_users MUST persist their API calls in github_tool_calls; results may be cached by upserting matching github_repositories, github_git_objects (for code hits when stored), and github_issues_pull_requests (for issue/PR hits) when identifiers are available.
- FK integrity MUST be enforced: repo_id referenced by git objects/issues/artifacts/tool_calls must exist; deleting a repo must be modeled as status='deleted' (soft delete) and must not break FK references.