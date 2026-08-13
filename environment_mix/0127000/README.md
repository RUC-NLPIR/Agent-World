# UIThub MCP Server — local MCP environment

This backend powers an MCP tool that fetches and filters GitHub repository contents (tree and/or file bodies) for downstream LLM use. It stores normalized repository/branch snapshots, directory trees, file metadata and optionally cached file contents, plus per-request query logs to enforce limits like max tokens and max file size.

Repository: https://github.com/janwilmake/uithub-mcp
Homepage: https://smithery.ai/server/@janwilmake/uithub-mcp

## Datastore

- `repositories.json` — Known GitHub repositories addressed by (owner, repo). Used to anchor branches, snapshots, and queries. (30 rows; fields: ['id', 'owner', 'name', 'html_url', 'default_branch', 'visibility', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(owner, name)
  - constraint: owner <> ''
  - constraint: name <> ''
- `repo_snapshots.json` — Materialized view of a repository at a specific branch HEAD (commit SHA). Serves as the immutable anchor for a directory tree and file records returned by getRepositoryContents. (31 rows; fields: ['id', 'repository_id', 'branch', 'head_sha', 'source', 'status', 'tree_root_path', 'tree_node_count', 'total_bytes_indexed', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'building', 'ready', 'failed', 'expired']
  - constraint: fk(repository_id) references repositories(id) on delete restrict
  - constraint: branch <> ''
  - constraint: head_sha <> ''
  - constraint: tree_root_path <> ''
- `repo_tree_nodes.json` — Normalized directory tree nodes (directories and files) for a given snapshot, used to return the tree structure and to filter by path/dir/ext/exclude rules. (29 rows; fields: ['id', 'snapshot_id', 'parent_node_id', 'node_type', 'path', 'name', 'depth', 'extension', 'size_bytes', 'blob_sha', 'mode', 'is_binary', 'created_at', 'updated_at'])
  - lifecycle `node_type`: ['dir', 'file']
  - constraint: fk(snapshot_id) references repo_snapshots(id) on delete cascade
  - constraint: fk(parent_node_id) references repo_tree_nodes(id) on delete cascade
  - constraint: unique(snapshot_id, path)
  - constraint: path <> ''
- `repo_file_contents.json` — Optional cached file contents for file nodes. Returned when omitFiles=false and subject to size/token budgets. (30 rows; fields: ['id', 'snapshot_id', 'tree_node_id', 'encoding', 'content_text', 'content_base64', 'byte_length', 'estimated_tokens', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `encoding`: ['utf-8', 'base64', 'binary']
  - constraint: fk(snapshot_id) references repo_snapshots(id) on delete cascade
  - constraint: fk(tree_node_id) references repo_tree_nodes(id) on delete cascade
  - constraint: unique(snapshot_id, tree_node_id)
  - constraint: byte_length >= 0
- `content_queries.json` — Per-call log of getRepositoryContents requests and the effective filters applied. Enables auditability, caching decisions, and enforcement of response limits (maxTokens, maxFileSize, omitFiles/omitTree). (35 rows; fields: ['id', 'repository_id', 'snapshot_id', 'owner', 'repo', 'branch', 'path', 'ext', 'dir', 'exclude_ext', 'exclude_dir', 'max_file_size_bytes', 'max_tokens', 'omit_files', 'omit_tree', 'status', 'result_tree_nodes', 'result_files_included', 'result_bytes_included', 'result_estimated_tokens', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'resolving_snapshot', 'filtering', 'completed', 'failed']
  - constraint: fk(repository_id) references repositories(id) on delete restrict
  - constraint: fk(snapshot_id) references repo_snapshots(id) on delete set null
  - constraint: owner <> ''
  - constraint: repo <> ''

## Business rules enforced by the tools

- getRepositoryContents must upsert repositories by unique(owner, name) before serving results.
- If branch is omitted in the tool call, the effective branch must resolve to repositories.default_branch; if that is null, default to 'main', then 'master' if 'main' does not exist (implementation-specific resolution against GitHub).
- A repo_snapshot must be created (status=queued) or reused (status=ready) for the resolved (repository_id, branch, head_sha). The tool must not return a tree from a snapshot unless status=ready.
- When omitTree=true, the response must not include any tree structure; when omitFiles=true, the response must not include any file contents. Both may be true.
- Filtering semantics: path, dir, exclude_dir are applied on repo_tree_nodes.path as prefix/path-segment matches; ext/excludeExt are applied against repo_tree_nodes.extension for node_type='file'.
- maxFileSize must exclude any file where repo_tree_nodes.size_bytes is known and greater than maxFileSize; if size_bytes is unknown, the implementation must fetch metadata before including contents.
- maxTokens is enforced as an upper bound on the sum of included repo_file_contents.estimated_tokens (or runtime tokenization if estimated_tokens is null). The tool must stop adding file contents once the budget would be exceeded.
- Only file nodes (repo_tree_nodes.node_type='file') may have repo_file_contents; attempts to associate contents with a dir node must be rejected.
- Binary files (repo_tree_nodes.is_binary=true or repo_file_contents.encoding='binary') must not be emitted as content_text; they may be omitted or returned as base64 depending on implementation defaults, but must still respect maxTokens/maxFileSize.
- Status transitions must follow the declared lifecycle graphs; e.g., repo_snapshots.ready cannot transition back to building, and content_queries.completed cannot transition to any other status.
- For a given snapshot, repo_tree_nodes.path must be unique; for a given snapshot and file node, repo_file_contents must be unique.
- Repositories marked disabled or deleted must not be served; content_queries for such repos must end in status=failed with an error_message.