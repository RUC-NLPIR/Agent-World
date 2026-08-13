# Github — local MCP environment

This backend models a GitHub-connected service that mirrors core GitHub entities (repositories, refs, commits, files, issues, pull requests, and comments) to support search, read, and write operations through the tool surface. It stores both locally-created objects (e.g., issues, PRs, comments, pushes) and externally-sourced metadata (e.g., repository details, commits, branches, tags) with lifecycle statuses and auditability for updates and merges.

Repository: https://github.com/smithery-ai/mcp-servers
Homepage: https://smithery.ai/server/@smithery-ai/github

## Datastore

- `gh_repositories.json` — GitHub repositories known to the system (owned, forked, or discovered via search). Stores metadata required for get_repository, create_repository, fork_repository and as the parent for issues/PRs/refs/commits/files. (28 rows; fields: ['id', 'github_repo_id', 'owner_login', 'name', 'full_name', 'description', 'visibility', 'default_branch', 'is_fork', 'parent_repository_id', 'readme_path', 'readme_sha', 'readme_content_base64', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(full_name)
  - constraint: unique(github_repo_id) WHERE github_repo_id IS NOT NULL
  - constraint: visibility IN ('public','private','internal')
  - constraint: owner_login <> ''
- `gh_git_refs.json` — Branches and tags (refs) for a repository. Supports list_branches, create_branch, list_tags, get_tag, and provides commit pointers for list_commits/get_commit. (30 rows; fields: ['id', 'repository_id', 'ref_type', 'name', 'full_ref', 'head_commit_sha', 'tag_object_sha', 'tag_message', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(repository_id, ref_type, name)
  - constraint: unique(repository_id, full_ref)
  - constraint: ref_type IN ('branch','tag')
  - constraint: length(head_commit_sha) = 40 WHERE head_commit_sha IS NOT NULL
- `gh_commits.json` — Commit objects for repositories. Supports get_commit and list_commits; also used when creating commits via create_or_update_file and push_files (recording resulting commit). (32 rows; fields: ['id', 'repository_id', 'sha', 'author_login', 'author_name', 'author_email', 'authored_at', 'committer_name', 'committer_email', 'committed_at', 'message', 'parent_shas', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['known', 'verified', 'orphaned']
  - constraint: unique(repository_id, sha)
  - constraint: length(sha) = 40
  - constraint: sha ~ '^[0-9a-f]{40}$'
- `gh_files.json` — Repository file/blobs as last fetched or written. Supports get_file_contents, create_or_update_file, push_files and provides concise hit metadata for search_code results (path/repo). (31 rows; fields: ['id', 'repository_id', 'path', 'branch_name', 'blob_sha', 'size_bytes', 'encoding', 'content_base64', 'last_commit_sha', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['present', 'deleted']
  - constraint: unique(repository_id, branch_name, path) WHERE branch_name IS NOT NULL
  - constraint: unique(repository_id, path) WHERE branch_name IS NULL
  - constraint: length(blob_sha) = 40 WHERE blob_sha IS NOT NULL
  - constraint: size_bytes >= 0 WHERE size_bytes IS NOT NULL
- `gh_issues.json` — Issues and pull requests share numbering in GitHub; this table stores issue-like fields and lifecycle. Supports search_issues, list_issues, get_issue, create_issue, update_issue, and acts as the parent for issue comments. (31 rows; fields: ['id', 'repository_id', 'github_issue_id', 'number', 'title', 'body', 'labels', 'assignees', 'creator_login', 'state', 'locked', 'closed_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `state`: ['open', 'closed']
  - constraint: unique(repository_id, number)
  - constraint: unique(github_issue_id) WHERE github_issue_id IS NOT NULL
  - constraint: number > 0
  - constraint: title <> ''
- `gh_pull_requests.json` — Pull requests for a repository. Supports list_pull_requests, get_pull_request, create_pull_request, update_pull_request, merge_pull_request, get_pull_request_files, get_pull_request_status, and get_pull_request_comments. Stores base/head refs and merge lifecycle; changed files are stored as an embedded list for this minimal model. (35 rows; fields: ['id', 'repository_id', 'github_pull_id', 'number', 'title', 'body', 'creator_login', 'base_branch', 'head_branch', 'head_repository_full_name', 'state', 'mergeable', 'merged_by_login', 'merged_at', 'merge_commit_sha', 'changed_files', 'review_status', 'status', 'created_at', 'updated_at'])
  - lifecycle `state`: ['open', 'closed', 'merged']
  - constraint: unique(repository_id, number)
  - constraint: unique(github_pull_id) WHERE github_pull_id IS NOT NULL
  - constraint: number > 0
  - constraint: title <> ''

## Business rules enforced by the tools

- search_repositories returns rows from gh_repositories filtered by a full-text index over (full_name, description); results must exclude status='deleted'.
- search_users is served from GitHub upstream and may be cached externally; this schema does not persist users beyond embedding logins in other tables.
- search_code returns matches from a code index built from gh_files.path and optionally gh_files.content_base64; if content_base64 is NULL due to size limits, search_code still returns path-level hits where available.
- get_repository must return gh_repositories plus associated gh_git_refs (branches/tags) and a tree listing derived from gh_files for that repository; README is served from gh_repositories.readme_* or via gh_files where path matches readme_path.
- create_repository inserts into gh_repositories with status='active', is_fork=false; full_name must be unique and visibility must be one of (public, private, internal).
- fork_repository creates a new gh_repositories row with is_fork=true and parent_repository_id pointing to the source; parent_repository_id must reference an existing gh_repositories row with status='active'.
- list_branches lists gh_git_refs where repository_id matches and ref_type='branch' and status='active'; list_tags similarly uses ref_type='tag'.
- create_branch inserts a gh_git_refs row with ref_type='branch'; it must point to an existing commit sha in gh_commits for that repository OR allow unknown sha but must be updated once the upstream API returns it.
- get_tag reads a gh_git_refs row with ref_type='tag' and returns tag metadata; annotated tag fields (tag_object_sha/tag_message) must be NULL for lightweight tags.
- list_commits returns gh_commits for a repository filtered by branch by joining gh_git_refs.head_commit_sha and walking parents if available; at minimum, it must support returning commits by sha ordering when parent graph is incomplete.
- get_commit returns a gh_commits row by (repository_id, sha); sha must be a 40-hex string.
- get_file_contents returns gh_files by (repository_id, path) and optional branch_name; if content_base64 is NULL, the implementation must fetch from upstream and then update gh_files.content_base64/blob_sha/size_bytes/updated_at.
- create_or_update_file upserts gh_files by (repository_id, branch_name, path); when updating, the provided current SHA must match gh_files.blob_sha (optimistic concurrency) and must be 40 characters.
- push_files creates/updates multiple gh_files rows and must also insert a gh_commits row for the resulting commit sha; gh_files.last_commit_sha must be set to that commit sha.
- list_issues returns gh_issues filtered by repository_id and state; it must exclude gh_issues.status='deleted'.
- search_issues performs full-text search over gh_issues.title/body and returns issues across repositories; it must support filtering by state and labels if provided by the upstream query syntax.
- get_issue reads gh_issues by (repository_id, number) or github_issue_id when available; number is required to be > 0.
- create_issue inserts gh_issues with state='open' and status='active'; number must be allocated uniquely within repository (unique(repository_id, number)).
- update_issue may change title/body/labels/assignees and may transition state open<->closed; if state becomes closed, closed_at must be set; if state becomes open, closed_at must be NULL.
- add_issue_comment persists the comment upstream; locally, comments are not stored in this minimal schema, so the implementation must read/write comments via GitHub API and may optionally cache them elsewhere.
- get_issue_comments fetches from upstream; this schema intentionally does not persist issue comments due to tool surface lacking comment identifiers for local mutation beyond creation.
- list_pull_requests returns gh_pull_requests filtered by repository_id and state; it must exclude status='deleted'.
- get_pull_request reads gh_pull_requests by (repository_id, number) or github_pull_id; it must also return base/head branch fields and merge-related fields.
- create_pull_request inserts gh_pull_requests with state='open', base_branch and head_branch required and non-empty; it must validate base_branch exists as an active gh_git_refs branch for the repository or allow creation but mark review_status='unknown' until refs are synced.
- update_pull_request may change title/body/state (open/closed); it must not set state='merged' directly (only merge_pull_request can do that).
- merge_pull_request transitions gh_pull_requests.state from 'open' to 'merged' and sets merged_at and merge_commit_sha; merge_commit_sha must be a 40-hex string and must be inserted/updated in gh_commits for the repository.
- get_pull_request_files returns gh_pull_requests.changed_files; if changed_files is NULL, implementation must fetch from upstream and then update the row.
- get_pull_request_status returns derived status from gh_pull_requests.review_status/mergeable/state; review_status must be one of (unknown, clean, dirty, blocked, draft) when present.
- update_pull_request_branch is not implemented; it must not mutate gh_pull_requests or gh_git_refs and should return a not-implemented error.
- get_pull_request_comments fetches from upstream; this schema intentionally does not persist PR review comments in order to keep collections within the required limit.
- All foreign keys must enforce referential integrity: gh_git_refs.repository_id, gh_commits.repository_id, gh_files.repository_id, gh_issues.repository_id, gh_pull_requests.repository_id must reference gh_repositories.id.