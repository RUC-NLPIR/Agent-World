# Gitingest MCP Server — local MCP environment

This backend caches and serves GitHub repository metadata, trees, and file contents to support read-only MCP tools: repository summary, tree listing, and selected file retrieval. It tracks repositories and branches, snapshots a specific commit SHA for consistency, stores file paths and optionally content, and records per-request fetch jobs to manage rate limits and caching.

Repository: https://github.com/puravparab/Gitingest-MCP
Homepage: https://smithery.ai/server/@puravparab/gitingest-mcp

## Datastore

- `github_repositories.json` — Canonical GitHub repositories addressed by (owner, repo). Stores high-level metadata used to locate branches and snapshots. (25 rows; fields: ['id', 'owner', 'name', 'full_name', 'default_branch', 'visibility', 'last_seen_at', 'created_at', 'updated_at'])
  - constraint: unique(owner, name)
  - constraint: full_name = owner || '/' || name
  - constraint: owner <> '' and name <> ''
- `repo_branches.json` — Branches for a repository and the latest known head commit SHA. Used to resolve optional tool param branch (or fall back to default branch). (32 rows; fields: ['id', 'repository_id', 'name', 'head_commit_sha', 'is_default', 'last_refreshed_at', 'created_at', 'updated_at'])
  - constraint: unique(repository_id, name)
  - constraint: at most one is_default=true per repository_id (enforced via partial unique index on (repository_id) where is_default=true)
  - constraint: name <> ''
- `repo_snapshots.json` — An immutable, consistent view of a repository at a specific commit SHA for a given branch name at fetch time. Stores token counts and README-derived summary for git_summary, and serves as a parent for tree and file entries. (39 rows; fields: ['id', 'repository_id', 'branch_name', 'commit_sha', 'readme_path', 'readme_summary', 'total_files', 'total_tokens', 'tokenizer', 'status', 'error_message', 'source_fetched_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'building', 'ready', 'failed', 'expired']
  - constraint: unique(repository_id, branch_name, commit_sha)
  - constraint: total_files >= 0
  - constraint: total_tokens >= 0
  - constraint: branch_name <> ''
- `snapshot_entries.json` — Tree entries (files and directories) for a specific snapshot. Supports git_tree (structure) and git_files (content retrieval for selected paths). (35 rows; fields: ['id', 'snapshot_id', 'path', 'parent_path', 'name', 'entry_type', 'blob_sha', 'size_bytes', 'language_hint', 'content_status', 'content_text', 'content_bytes_base64', 'content_fetched_at', 'tokens_estimate', 'created_at', 'updated_at'])
  - lifecycle `content_status`: ['absent', 'fetching', 'available', 'too_large', 'binary', 'error']
  - constraint: unique(snapshot_id, path)
  - constraint: path <> ''
  - constraint: name <> ''
  - constraint: size_bytes is null or size_bytes >= 0
- `fetch_jobs.json` — Operational log of GitHub fetch/build work triggered by tool calls. Used for deduplication, throttling, and diagnosing failures (not directly exposed by tools but required by a real backend). (31 rows; fields: ['id', 'repository_id', 'snapshot_id', 'job_type', 'requested_branch', 'requested_file_paths', 'status', 'attempt', 'http_status', 'rate_limit_remaining', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: attempt >= 1
  - constraint: http_status is null or (http_status >= 100 and http_status <= 599)
  - constraint: rate_limit_remaining is null or rate_limit_remaining >= 0
  - constraint: job_type in ('resolve_branch','build_snapshot','fetch_tree','fetch_file_contents','summarize_readme')

## Business rules enforced by the tools

- For git_summary(owner, repo, branch): resolve github_repositories by (owner, name). If missing, create it; if branch is null, use repo.default_branch if present else create/refresh a repo_branches row marked is_default=true once discovered.
- For any tool call with a branch value, repo_branches.name must match exactly; if not present, create repo_branches with head_commit_sha fetched from GitHub; update last_refreshed_at.
- All reads for git_tree and git_files must be served from a single repo_snapshots row pinned to a commit_sha; if no ready snapshot exists for (repository_id, branch_name, head_commit_sha), create a queued snapshot and corresponding fetch_jobs to build it.
- repo_snapshots.status may transition only according to the declared lifecycle; snapshot_entries may be inserted/updated only while the parent snapshot is in status building; once snapshot is ready, entry structure (path, entry_type, blob_sha) is immutable.
- git_tree(owner, repo, branch) returns snapshot_entries filtered by snapshot_id where entry_type in ('file','dir','symlink','submodule'); ordering is by path asc; it must not return entries from snapshots not in status ready unless the implementation explicitly supports partial results.
- git_files(owner, repo, file_paths, branch) must validate file_paths is a non-empty array; each requested path must exist as a snapshot_entries row with entry_type='file' in the ready snapshot or be reported as not found; directories cannot be returned as file content.
- When caching content for git_files, set content_status to fetching before retrieval; on success set to available and store content_text for text files; if file exceeds max size, set content_status=too_large and do not store content; if detected binary, set content_status=binary and do not store content_text.
- total_files on repo_snapshots equals count(snapshot_entries where entry_type='file') for that snapshot once ready; total_tokens equals sum(tokens_estimate) over cached/estimated file entries and must be >= 0.
- Uniqueness constraints must be enforced to deduplicate concurrent calls: github_repositories(owner,name), repo_branches(repository_id,name), repo_snapshots(repository_id,branch_name,commit_sha), snapshot_entries(snapshot_id,path).
- FK integrity must be enforced: deleting a github_repositories row is disallowed if referenced by repo_branches, repo_snapshots, or fetch_jobs; deleting a repo_snapshots row cascades to snapshot_entries and fetch_jobs.snapshot_id only if snapshot status is expired.