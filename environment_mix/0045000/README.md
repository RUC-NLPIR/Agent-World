# Private GitHub Search — local MCP environment

This backend powers a private GitHub repository search service. It stores repository configuration, indexed snapshots of files/issues/commits, and logs each search/read request for auditing, rate limiting, and reproducibility of results over time.

Repository: https://github.com/Hint-Services/obsidian-github-mcp
Homepage: https://smithery.ai/server/@Hint-Services/mcp-private-github-search

## Datastore

- `workspaces.json` — Tenant/workspace boundary for API usage, access control, and configuration of a single "configured repository" per workspace (as implied by the tool surface). (18 rows; fields: ['id', 'name', 'configured_repo_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: configured_repo_id references repositories.id
- `repositories.json` — Configured GitHub repositories and credentials metadata (tokens stored by reference to a secret store). This is the authoritative repo config that the four tools operate on. (18 rows; fields: ['id', 'workspace_id', 'github_owner', 'github_repo', 'default_branch', 'installation_type', 'credential_secret_ref', 'status', 'last_indexed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: foreign key(workspace_id) references workspaces.id
  - constraint: unique(workspace_id, github_owner, github_repo)
  - constraint: default_branch != ''
- `repo_content_index.json` — Materialized index of repository content to serve fast search and file reads without calling GitHub for every request. Stores the latest snapshot per path plus lightweight searchable text. (18 rows; fields: ['id', 'repo_id', 'kind', 'path', 'blob_sha', 'file_size_bytes', 'language', 'content_text', 'issue_number', 'issue_state', 'issue_title', 'issue_body_text', 'commit_sha', 'commit_author', 'commit_message', 'commit_timestamp', 'commit_files_changed', 'source_url', 'status', 'indexed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'deleted']
  - constraint: foreign key(repo_id) references repositories.id
  - constraint: check(kind in ('file','issue','commit'))
  - constraint: check((kind='file' and path is not null) or (kind<>'file' and path is null))
  - constraint: check((kind='issue' and issue_number is not null) or (kind<>'issue' and issue_number is null))
- `api_keys.json` — API keys used by clients (e.g., MCP host) to access the service, with per-key quotas and auditability. (18 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'status', 'rate_limit_per_minute', 'daily_request_quota', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: foreign key(workspace_id) references workspaces.id
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: check(rate_limit_per_minute between 1 and 6000)
- `request_logs.json` — Immutable audit log of tool invocations (searchFiles, searchIssues, getFileContents, getCommitHistory) for debugging, analytics, and quota enforcement. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'repo_id', 'tool_name', 'parameters_json', 'status', 'error_code', 'error_message', 'result_count', 'duration_ms', 'client_ip', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'succeeded', 'failed', 'rate_limited']
  - constraint: foreign key(workspace_id) references workspaces.id
  - constraint: foreign key(api_key_id) references api_keys.id
  - constraint: foreign key(repo_id) references repositories.id
  - constraint: check(duration_ms is null or duration_ms >= 0)

## Business rules enforced by the tools

- All tools operate on the caller's workspace.configured_repo_id; if it is null or points to a repositories row not in status='active', the request must fail with error_code='REPO_NOT_CONFIGURED' or 'REPO_DISABLED'.
- For every tool invocation, a request_logs row must be created with tool_name set appropriately and parameters_json exactly matching the received JSON (empty object for this tool surface).
- API authentication must resolve an api_keys row by key_hash; only api_keys.status='active' and workspaces.status='active' are allowed to execute tools.
- Rate limits: if the number of request_logs for a given api_key_id in the trailing 60 seconds exceeds api_keys.rate_limit_per_minute, the request must be rejected and logged with status='rate_limited'.
- Daily quota: if the number of request_logs with status in ('succeeded','failed') for a given api_key_id in the current UTC day reaches api_keys.daily_request_quota, subsequent requests must be rejected and logged with status='rate_limited' and error_code='DAILY_QUOTA_EXCEEDED'.
- searchFiles must query repo_content_index where repo_id matches, kind='file', status='active', using content_text and/or path for matching; results must not include rows with status in ('stale','deleted') unless explicitly running an internal reindex/debug mode.
- searchIssues must query repo_content_index where repo_id matches, kind='issue', status='active', using issue_title and issue_body_text for matching; results must not include deleted issues.
- getFileContents must resolve a file by path within repo_content_index (kind='file') or fetch from GitHub using repositories.credential_secret_ref; if fetched content differs from blob_sha, the corresponding repo_content_index row must be updated (blob_sha, content_text, file_size_bytes, indexed_at) and any previously active row for that path must remain unique.
- getCommitHistory must read commits from repo_content_index where kind='commit' and commit_timestamp >= now() - interval 'X days' (service default if X is not provided by tool surface), returning commit_files_changed including diffs/patch_text possibly truncated; commit entries older than retention (e.g., 180 days) may be marked status='stale' or deleted by maintenance.
- FK integrity: repositories.workspace_id must equal workspaces.id; request_logs.repo_id must belong to request_logs.workspace_id via repositories.workspace_id; requests violating this must be rejected and logged with status='failed' and error_code='FORBIDDEN_REPO'.