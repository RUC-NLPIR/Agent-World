# Obsidian GitHub — local MCP environment

This backend stores connections to GitHub repositories that represent Obsidian vaults, plus cached copies of files, commits, and issues/discussions to support fast search and history retrieval. Main workflows are: register a vault repo + credentials, periodically sync files/commits/issues from GitHub, then serve read APIs for file contents, searching, and commit history with optional cache refresh.

Repository: https://github.com/Hint-Services/obsidian-github-mcp
Homepage: https://smithery.ai/server/@Hint-Services/obsidian-github-mcp

## Datastore

- `workspaces.json` — Tenant/workspace owning one or more Obsidian vault repositories and API keys. (12 rows; fields: ['id', 'name', 'status', 'plan', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: name length between 1 and 120
- `api_keys.json` — API keys used by clients to access tools; also carries per-key rate limits and last-used metadata. (12 rows; fields: ['id', 'workspace_id', 'name', 'key_prefix', 'key_hash', 'status', 'rate_limit_per_minute', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_prefix)
  - constraint: rate_limit_per_minute between 1 and 6000
- `vault_repos.json` — A GitHub repository representing an Obsidian vault, including authentication method and sync/caching state. (12 rows; fields: ['id', 'workspace_id', 'github_owner', 'github_repo', 'default_branch', 'visibility', 'auth_type', 'auth_ref', 'status', 'last_sync_at', 'last_sync_commit_sha', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'syncing', 'error', 'disabled']
  - constraint: unique(workspace_id, github_owner, github_repo)
  - constraint: github_owner length between 1 and 39
  - constraint: github_repo length between 1 and 100
  - constraint: default_branch length between 1 and 255
- `vault_files.json` — Cached file index and (optionally) content snapshots for files in a vault repo branch to support getFileContents and searchFiles. (18 rows; fields: ['id', 'vault_repo_id', 'branch', 'path', 'name', 'extension', 'size_bytes', 'sha', 'content_encoding', 'content_text', 'content_base64', 'content_truncated', 'indexed_at', 'deleted', 'created_at', 'updated_at'])
  - constraint: unique(vault_repo_id, branch, path)
  - constraint: size_bytes is null or size_bytes >= 0
  - constraint: content_truncated in (true,false)
  - constraint: if content_text is not null then content_encoding='utf-8'
- `repo_activity.json` — Cached commits and issues/discussions for a vault repo. Stores enough fields to power getCommitHistory and searchIssues and allow limited diff viewing. (19 rows; fields: ['id', 'vault_repo_id', 'activity_type', 'github_node_id', 'github_number', 'sha', 'title', 'body_text', 'author_login', 'state', 'labels', 'committed_at', 'summary', 'message', 'files_changed', 'additions', 'deletions', 'patches', 'url', 'status', 'indexed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'deleted']
  - constraint: unique(vault_repo_id, activity_type, sha) where activity_type='commit'
  - constraint: unique(vault_repo_id, activity_type, github_number) where activity_type in ('issue','discussion')
  - constraint: github_number is null or github_number > 0
  - constraint: files_changed is null or files_changed >= 0

## Business rules enforced by the tools

- Every tool call must authenticate via an active api_keys record; revoked keys are rejected.
- A workspace in status='deleted' cannot be accessed; status='suspended' allows reads only if explicitly enabled by policy (default: reject).
- Each tool call must be scoped to exactly one vault_repos record resolved by configuration (e.g., default vault per workspace); if multiple vaults exist, the server must select deterministically or require configuration.
- getFileContents reads from vault_files by (vault_repo_id, branch, path); if cached content is missing/stale and the vault_repo is active, the server may fetch from GitHub and upsert vault_files, updating sha/indexed_at/updated_at.
- searchFiles queries vault_files across name/path/content_text; deleted=true rows are excluded. Content search must only scan content_text and must not attempt to decode binary content_base64.
- searchIssues queries repo_activity where activity_type in ('issue','discussion'); status!='deleted'. Filtering by state/labels is applied over state and labels fields; text search applies over title/body_text/author_login.
- getCommitHistory queries repo_activity where activity_type='commit' ordered by committed_at desc; status!='deleted'. If patches are requested by implementation, they may be fetched and stored in patches subject to size limits.
- Cache size limits: vault_files.content_text must not exceed 1,000,000 characters per file; if exceeded, content_truncated=true and only the prefix is stored. For binaries, content_base64 must not exceed 5,000,000 characters; otherwise store no content and mark content_truncated=true.
- Sync integrity: vault_repos.last_sync_commit_sha must refer to an existing commit sha in repo_activity for that vault when last_sync_at is not null.
- FK integrity is enforced: deleting a workspace is a soft delete (status='deleted'); dependent records remain but are inaccessible. A vault_repo may be disabled without deleting cached data.