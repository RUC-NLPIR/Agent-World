# GitHub Repo MCP Server — local MCP environment

This backend indexes GitHub repositories (by URL) into a lightweight content cache so directory listings and file contents can be served quickly without repeatedly calling GitHub. The main workflow is: resolve repoUrl -> ensure a snapshot of a specific ref is available -> read directories/files from stored tree nodes and blobs; optionally trigger/track refresh jobs when cached data is stale.

Repository: https://github.com/Ryan0204/github-repo-mcp
Homepage: https://smithery.ai/server/@Ryan0204/github-repo-mcp

## Datastore

- `repositories.json` — Canonical GitHub repositories identified by repoUrl, with parsed owner/name and default ref configuration used for browsing. (18 rows; fields: ['id', 'repo_url', 'host', 'owner', 'name', 'default_ref', 'visibility', 'status', 'last_indexed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(repo_url)
  - constraint: unique(host, owner, name)
  - constraint: repo_url must be a valid URI and match host=github.com
  - constraint: status != 'deleted' implies updated_at is set on changes
- `repo_snapshots.json` — Materialized snapshots of a repository at a specific ref/commit used to serve directory listings and file fetches deterministically. (18 rows; fields: ['id', 'repository_id', 'ref', 'commit_sha', 'root_tree_sha', 'status', 'error_message', 'indexed_files_count', 'indexed_dirs_count', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'indexing', 'ready', 'failed', 'expired']
  - constraint: foreign key(repository_id) references repositories(id) on delete restrict
  - constraint: unique(repository_id, ref, commit_sha)
  - constraint: commit_sha length = 40 hex
  - constraint: root_tree_sha length = 40 hex
- `repo_nodes.json` — Indexed tree nodes (directories and files) for a given repo snapshot, enabling fast directory listings and path lookups. (18 rows; fields: ['id', 'snapshot_id', 'path', 'name', 'parent_path', 'kind', 'git_sha', 'size_bytes', 'is_binary', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key(snapshot_id) references repo_snapshots(id) on delete cascade
  - constraint: unique(snapshot_id, path)
  - constraint: path must not start with '/' and must not contain '..'
  - constraint: kind='dir' implies size_bytes is null and is_binary=false
- `repo_blobs.json` — Deduplicated file contents keyed by git blob SHA; used by getRepoFile to return content without re-fetching from GitHub. (18 rows; fields: ['id', 'git_sha', 'encoding', 'content', 'content_size_bytes', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'purged']
  - constraint: unique(git_sha)
  - constraint: git_sha length = 40 hex
  - constraint: content_size_bytes >= 0
  - constraint: encoding='utf-8' implies content is valid UTF-8

## Business rules enforced by the tools

- Tool getRepoAllDirectories(repoUrl) must resolve repositories by normalized repo_url; if not present, create repositories row with status='active' and enqueue/create a repo_snapshots row at ref=default_ref with status='queued'.
- Tool getRepoAllDirectories(repoUrl) must serve results from the latest repo_snapshots row for the repository where status='ready' and (expires_at is null or expires_at > now); if none exists, it must trigger snapshot creation (status='queued') and return a retriable error or empty list depending on product behavior.
- Tool getRepoDirectories(repoUrl, path) must normalize path (no leading '/', no '..', collapse duplicate slashes); it must locate a repo_nodes row with kind='dir' at that path for the latest ready snapshot, then list immediate children where parent_path equals that directory path and status='active'.
- Tool getRepoAllDirectories(repoUrl) returns all repo_nodes where kind='dir' and status='active' for the latest ready snapshot; root directory is represented by path='' and parent_path is null.
- Tool getRepoFile(repoUrl, path) must normalize path; it must locate a repo_nodes row with kind='file' at that path for the latest ready snapshot and then fetch content via repo_blobs.git_sha = repo_nodes.git_sha where repo_blobs.status='available'.
- When indexing a snapshot, every repo_nodes row must belong to exactly one snapshot_id; paths must be unique per snapshot (unique(snapshot_id, path)).
- A repo_snapshots row can only transition through the declared lifecycle transitions; particularly, status='ready' can only be reached from 'indexing', and 'failed' must include error_message.
- If repositories.status is 'disabled' or 'deleted', all tools must refuse to index new snapshots for that repository and must not serve content from snapshots created after the disable/delete time.
- Blob caching is content-addressed: inserting into repo_blobs with an existing git_sha must be idempotent and must not change existing content for that sha.
- To prevent abuse, the implementation must enforce a maximum file size fetched/stored (e.g., content_size_bytes <= 10_000_000); files exceeding the limit must be stored as metadata only in repo_nodes with is_binary=true and must not create/overwrite repo_blobs content.