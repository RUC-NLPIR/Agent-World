# GitLab — local MCP environment

This backend models a GitLab-like code hosting service focused on projects (repositories), their git references (branches), versioned files, and collaboration artifacts (issues and merge requests). The main workflows are creating/searching projects, forking, creating branches, reading file contents, and committing file changes (single-file or multi-file) which produce new commit snapshots used by merge requests.

Repository: https://github.com/smithery-ai/reference-servers
Homepage: https://smithery.ai/server/@smithery-ai/gitlab

## Datastore

- `users.json` — Accounts and identities that own projects and author actions (commits, issues, merge requests). (18 rows; fields: ['id', 'username', 'display_name', 'email', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'blocked', 'deleted']
  - constraint: unique(username)
  - constraint: email is unique where email is not null
  - constraint: username length between 1 and 255
- `projects.json` — GitLab projects/repositories, including fork relationships and default branch configuration. (18 rows; fields: ['id', 'owner_user_id', 'namespace', 'name', 'path', 'description', 'visibility', 'default_branch', 'forked_from_project_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'pending_deletion', 'deleted']
  - constraint: unique(namespace, path)
  - constraint: default_branch length between 1 and 255
  - constraint: visibility in ('private','internal','public')
  - constraint: forked_from_project_id must reference an active or archived project
- `branches.json` — Git branch references for a project, each pointing to a commit snapshot (head). (19 rows; fields: ['id', 'project_id', 'name', 'head_commit_id', 'protected', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(project_id, name)
  - constraint: name length between 1 and 255
  - constraint: project must be status='active' to create branch
  - constraint: cannot set status='deleted' if name equals project's default_branch (unless project pending_deletion)
- `commits.json` — Immutable commit snapshots storing file trees for each project; created via create_or_update_file and push_files. (17 rows; fields: ['id', 'project_id', 'git_sha', 'parent_commit_id', 'author_user_id', 'message', 'status', 'tree', 'created_at', 'updated_at'])
  - lifecycle `status`: ['created', 'verified', 'rejected']
  - constraint: unique(project_id, git_sha)
  - constraint: message length between 1 and 2000
  - constraint: tree must be a valid object and total materialized size per commit <= 50_000_000 bytes
  - constraint: parent_commit_id must belong to same project when not null
- `issues.json` — Issue tracker items within a project. (17 rows; fields: ['id', 'project_id', 'iid', 'title', 'description', 'author_user_id', 'assignee_user_id', 'state', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(project_id, iid)
  - constraint: iid >= 1
  - constraint: title length between 1 and 255
  - constraint: project must be status in ('active','archived') to create issue
- `merge_requests.json` — Merge requests between branches in a project (or across forks), tracking source/target and head commits. (18 rows; fields: ['id', 'target_project_id', 'source_project_id', 'iid', 'title', 'description', 'author_user_id', 'source_branch', 'target_branch', 'source_head_commit_id', 'target_base_commit_id', 'state', 'merge_status', 'status', 'created_at', 'updated_at'])
  - lifecycle `state`: ['opened', 'merged', 'closed']
  - constraint: unique(target_project_id, iid)
  - constraint: iid >= 1
  - constraint: title length between 1 and 255
  - constraint: source_project_id and target_project_id must both exist and be status in ('active','archived')

## Business rules enforced by the tools

- search_repositories returns projects where status != 'deleted' and (visibility='public' OR owner_user_id is the caller), and supports full-text matching over namespace, name, path, and description.
- create_repository creates a projects row with status='active', visibility defaulting to 'private' when unspecified, and creates an initial commit plus a default branch pointing to that commit.
- fork_repository creates a new projects row with forked_from_project_id set to the upstream project, copies the upstream default branch and head commit as the fork's initial branch head, and enforces unique(namespace, path).
- create_branch requires the project status='active', the branch name to be unique within the project, and sets head_commit_id to the specified ref commit (typically the head of an existing branch).
- get_file_contents reads from the tree of the commit referenced by a branch (or specified commit) and returns either file content (for type='file') or a directory listing (for type='dir'); requests for non-existent paths must be 404-like errors.
- create_or_update_file creates a new commit with parent_commit_id equal to the current head of the target branch, updates exactly one file path in the tree snapshot (creating directories as needed), and moves the branch head_commit_id to the new commit atomically.
- push_files creates a single new commit that applies multiple file operations (create/update/delete) to the parent commit tree snapshot and advances the branch head_commit_id atomically; if any file operation is invalid (e.g., delete missing file, path traversal, oversized content), the entire push fails.
- Commit tree paths must be normalized, must not contain '..' segments, and must be unique case-sensitively within a commit snapshot.
- create_issue allocates the next iid per project using a transaction/sequence and creates an issues row with state='opened' and status='active'.
- create_merge_request allocates the next iid per target_project_id, snapshots source_head_commit_id and target_base_commit_id from the current heads of the referenced branches, and computes merge_status as 'unchecked' at creation time.
- Deleting (status='deleted') any entity is a soft-delete; read operations must exclude status='deleted' by default.
- A project's default_branch must always refer to an existing active branch name for that project while project.status in ('active','archived').
- Branches.head_commit_id must always reference a commits row in the same project; updates to head_commit_id must occur only via commit creation (create_or_update_file/push_files) or branch creation.