# Azure DevOps Integration — local MCP environment

This backend models an Azure DevOps organization integration that mirrors key Azure DevOps entities (projects, work items, pull requests, and wiki pages) locally for fast listing, retrieval, and mutation via API tools. Workflows include syncing projects, creating/updating work items and pull requests (including comments and diffs), and creating/editing wiki pages, with lifecycle status tracked for work items and pull requests.

Repository: https://github.com/mmruesch12/azdo-mcp
Homepage: https://smithery.ai/server/@mmruesch12/azdo-mcp

## Datastore

- `projects.json` — Azure DevOps projects accessible to the integration. Used by list_projects/get_project and as the parent entity for work items, pull requests, and wiki pages. (18 rows; fields: ['id', 'ado_project_id', 'organization', 'name', 'description', 'visibility', 'state', 'default_repository_id', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `state`: ['active', 'disabled', 'deleting', 'deleted']
  - constraint: unique(organization, ado_project_id)
  - constraint: unique(organization, name)
  - constraint: state in ('active','disabled','deleting','deleted')
  - constraint: name <> ''
- `work_items.json` — Azure DevOps work items (bugs, tasks, user stories, etc.) mirrored locally. Supports list_work_items/get_work_item/create_work_item. (18 rows; fields: ['id', 'project_id', 'ado_work_item_id', 'work_item_type', 'title', 'description', 'assigned_to', 'status', 'area_path', 'iteration_path', 'tags', 'url', 'source', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['new', 'active', 'resolved', 'closed', 'removed']
  - constraint: fk(project_id) references projects.id on delete cascade
  - constraint: unique(project_id, ado_work_item_id)
  - constraint: ado_work_item_id is null or ado_work_item_id > 0
  - constraint: title <> ''
- `pull_requests.json` — Azure DevOps pull requests in Git repositories. Supports list_pull_requests/get_pull_request/create_pull_request/update_pull_request/get_pull_request_diff. (17 rows; fields: ['id', 'project_id', 'repository_id', 'ado_pull_request_id', 'title', 'description', 'source_branch', 'target_branch', 'created_by', 'status', 'is_draft', 'merge_status', 'work_item_ids', 'last_diff_etag', 'last_diff_cached_at', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'active', 'completed', 'abandoned']
  - constraint: fk(project_id) references projects.id on delete cascade
  - constraint: unique(project_id, repository_id, ado_pull_request_id)
  - constraint: ado_pull_request_id is null or ado_pull_request_id > 0
  - constraint: repository_id <> ''
- `pull_request_comments.json` — Comments on pull requests, including those created via create_pull_request_comment. Stored per PR and optionally per thread if the upstream API supports it. (18 rows; fields: ['id', 'pull_request_id', 'ado_thread_id', 'ado_comment_id', 'author', 'content', 'status', 'published_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(pull_request_id) references pull_requests.id on delete cascade
  - constraint: content <> ''
  - constraint: ado_thread_id is null or ado_thread_id > 0
  - constraint: ado_comment_id is null or ado_comment_id > 0
- `wiki_pages.json` — Azure DevOps wiki pages per project, including page content and versioning metadata. Supports create_wiki_page/edit_wiki_page. (18 rows; fields: ['id', 'project_id', 'wiki_id', 'path', 'title', 'content_markdown', 'ado_version', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(project_id) references projects.id on delete cascade
  - constraint: unique(project_id, wiki_id, path)
  - constraint: path <> ''
  - constraint: content_markdown <> ''

## Business rules enforced by the tools

- list_projects returns projects where state != 'deleted' and organization matches the configured integration organization.
- get_project must resolve by either (projects.id) or (organization, ado_project_id) depending on caller input; if not found, return 404.
- list_work_items returns work_items filtered by project_id when provided by implementation context; records with status='removed' may be excluded by default.
- get_work_item must resolve by either internal id or (project_id, ado_work_item_id); if ado_work_item_id is provided it must be > 0.
- create_work_item creates a row in work_items with source='created_via_api' and status in {'new','active'}; title and work_item_type are required; project_id must exist.
- list_pull_requests returns pull_requests filtered by project_id/repository_id when provided; by default excludes status='abandoned' only if the upstream API defaults to active (implementation choice must be consistent).
- get_pull_request must resolve by either internal id or (project_id, repository_id, ado_pull_request_id); ado_pull_request_id must be > 0 when used.
- create_pull_request requires description, source_branch, target_branch; it stores work_item_ids if supplied and each id must reference an existing work item in the same project when the system has it locally (otherwise allow but mark as external reference).
- update_pull_request may modify title, description, target_branch, status, and is_draft; status transitions must follow pull_requests.lifecycle.transitions and completed/abandoned are terminal.
- create_pull_request_comment requires pull_request_id to exist and content to be non-empty; comments cannot be added to pull requests with status in {'completed','abandoned'} unless the upstream permits it (if upstream rejects, store nothing and surface error).
- get_pull_request_diff fetches diff from upstream and may cache metadata in pull_requests.last_diff_etag and pull_requests.last_diff_cached_at; it must not mutate diff content into other collections (kept as ephemeral payload) unless explicitly added later.
- create_wiki_page requires project_id and path and content_markdown; path must be unique per (project_id, wiki_id).
- edit_wiki_page requires the wiki page to exist and status='active'; if ado_version is tracked, edits must enforce optimistic concurrency by requiring the expected ado_version to match before updating and then incrementing/storing the new version.