# Atlassian Bitbucket Integration — local MCP environment

This backend models a Bitbucket-integrated API that lets authenticated users enumerate accessible workspaces, browse repositories, list/read/create pull requests, and read/add pull request comments. It also stores search requests and their result snapshots to support pagination and consistent responses across repository/PR/commit/code search scopes.

Repository: https://github.com/aashari/mcp-server-atlassian-bitbucket
Homepage: https://smithery.ai/server/@aashari/mcp-server-atlassian-bitbucket

## Datastore

- `workspaces.json` — Bitbucket workspaces accessible via the integration; used as the root container for repositories and searches. Stores slugs and core metadata returned by Bitbucket. (32 rows; fields: ['id', 'slug', 'name', 'bb_uuid', 'workspace_type', 'website', 'links', 'status', 'synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'revoked']
  - constraint: unique(slug)
  - constraint: slug length >= 1
  - constraint: status in ('active','archived','revoked')
- `repositories.json` — Repositories within a workspace; used to satisfy list/get repository and as the parent for pull requests and scoped searches. (37 rows; fields: ['id', 'workspace_id', 'slug', 'name', 'bb_uuid', 'description', 'is_private', 'language', 'size_bytes', 'fork_policy', 'main_branch', 'owner_display_name', 'links', 'status', 'created_on', 'updated_on', 'synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, slug)
  - constraint: slug length >= 1
  - constraint: size_bytes is null or size_bytes >= 0
- `pull_requests.json` — Pull requests for repositories; supports listing, retrieval, and creation. Also serves as the parent entity for PR comments. (34 rows; fields: ['id', 'repository_id', 'bb_pr_id', 'title', 'description', 'state', 'author_display_name', 'author_account_id', 'source_branch', 'destination_branch', 'close_source_branch', 'links', 'created_on', 'updated_on', 'merged_on', 'synced_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `state`: ['OPEN', 'MERGED', 'DECLINED', 'SUPERSEDED']
  - constraint: fk(repository_id) references repositories(id) on delete cascade
  - constraint: unique(repository_id, bb_pr_id)
  - constraint: bb_pr_id > 0
  - constraint: title length >= 1
- `pull_request_comments.json` — Comments and inline review notes for pull requests; supports listing and adding comments (general or inline with path/line). (35 rows; fields: ['id', 'pull_request_id', 'bb_comment_id', 'content', 'author_display_name', 'author_account_id', 'inline_path', 'inline_line', 'links', 'status', 'created_on', 'updated_on', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(pull_request_id) references pull_requests(id) on delete cascade
  - constraint: content length >= 1
  - constraint: inline_line is null or inline_line > 0
  - constraint: ((inline_path is null) and (inline_line is null)) or ((inline_path is not null) and (inline_line is not null))
- `search_requests.json` — Captured search operations for a workspace (and optionally a repository) across scopes; stores parameters, pagination cursors, and a snapshot of result ids/metadata to serve consistent paged responses. (36 rows; fields: ['id', 'workspace_id', 'repository_id', 'scope', 'query', 'limit', 'cursor_in', 'cursor_out', 'result_items', 'status', 'error_message', 'executed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: repository_id is null or fk(repository_id) references repositories(id) on delete restrict
  - constraint: limit between 1 and 100
  - constraint: scope in ('repositories','pullrequests','commits','code','all')

## Business rules enforced by the tools

- list_workspaces(limit,cursor) reads from workspaces ordered by slug; limit must be 1..100 (default 25) and cursor must be a valid opaque pagination token representing the last returned workspace.slug.
- get_workspace(workspaceSlug) resolves workspaces.slug = workspaceSlug and status != 'revoked'; otherwise return not found/forbidden.
- list_repositories(workspaceSlug,query,sort,role,limit,cursor) resolves workspace by slug, then filters repositories by workspace_id and status='active'; query performs case-insensitive match on name/description; sort only allows 'name','created_on','updated_on' optionally prefixed by '-', otherwise reject; role filtering is enforced by upstream Bitbucket permissions and may be stored/derived but must not return repos the user lacks access to.
- get_repository(workspaceSlug,repoSlug) resolves workspace then repository by (workspace_id, slug); status must not be 'deleted'.
- list_pull_requests(workspaceSlug,repoSlug,state,query,limit,cursor) resolves repository then filters pull_requests by repository_id; if state provided it must be one of OPEN|MERGED|DECLINED|SUPERSEDED; query performs text search over title/description/author_display_name (or passes through to Bitbucket query syntax); limit 1..100 (default 25).
- get_pull_request(workspaceSlug,repoSlug,prId) parses prId as integer > 0 and resolves pull_requests.unique(repository_id, bb_pr_id).
- list_pr_comments(workspaceSlug,repoSlug,prId,limit,cursor) resolves pull request then returns pull_request_comments where pull_request_id matches and status='active', ordered by created_on/id; limit 1..100 (default 25).
- add_pr_comment(workspaceSlug,repoSlug,prId,content,inline) requires content length >= 1; if inline provided, both inline.path and inline.line must be present and inline.line > 0; creates a new pull_request_comments row in status='active' and writes through to Bitbucket, storing bb_comment_id and created_on on success.
- pull_requests_create(workspaceSlug,repoSlug,title,sourceBranch,destinationBranch,description,closeSourceBranch) requires title and sourceBranch length >= 1; destinationBranch defaults to repository.main_branch when omitted, otherwise must be non-empty; creates a pull_requests row with state='OPEN' on successful upstream creation; closeSourceBranch defaults to false.
- search(workspaceSlug,repoSlug,query,scope,limit,cursor) creates a search_requests row; limit must be 1..100; scope defaults to 'all'; if scope='pullrequests' then repoSlug is required and must resolve to a repository in the workspace; if scope='code' then query is required and non-empty; cursor semantics must be preserved: for repos/PRs it is an opaque cursor string, for code it is a positive integer page number encoded as string.
- FK integrity must be maintained: repositories cannot exist without a workspace; pull_requests cannot exist without a repository; comments cannot exist without a pull_request.
- State transitions are enforced: pull_requests.state cannot move away from MERGED/DECLINED/SUPERSEDED; search_requests.status cannot move from succeeded/failed back to running.