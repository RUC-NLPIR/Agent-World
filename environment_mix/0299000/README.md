# Yunxiao DevOps Server — local MCP environment

This backend stores Yunxiao (Alibaba Cloud DevOps) organization data spanning identity (users/orgs), code management (repositories/branches/files/change requests), project management (projects/work items), pipelines (definitions, runs, jobs, logs), and package management (artifact repositories and artifacts). Core workflows include browsing and mutating Codeup repos (branches/files/MRs), searching projects/work items, running and inspecting pipelines (runs/jobs/logs), and listing artifacts in package repositories under an organization context derived from an access token.

Repository: https://github.com/aliyun/alibabacloud-devops-mcp-server
Homepage: https://smithery.ai/server/@aliyun/alibabacloud-devops-mcp-server

## Datastore

- `identity.json` — Tenancy and identity model: organizations, users, memberships, and API tokens used to resolve the current user/organization for requests. (20 rows; fields: ['id', 'entity_type', 'status', 'organization_id', 'user_id', 'external_aliyun_uid', 'display_name', 'email', 'role', 'token_hash', 'token_last4', 'token_scopes', 'expires_at', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: entity_type in ('organization','user','membership','api_token')
  - constraint: unique(external_aliyun_uid) WHERE entity_type='user' AND external_aliyun_uid IS NOT NULL
  - constraint: unique(organization_id, user_id) WHERE entity_type='membership'
  - constraint: organization_id IS NOT NULL WHERE entity_type IN ('membership','api_token')
- `codeup.json` — Code management objects: repositories, branches, files (head state), commits metadata, and change requests with comments and patch sets. (32 rows; fields: ['id', 'entity_type', 'status', 'organization_id', 'repository_id', 'project_id', 'name', 'default_branch', 'branch_name', 'head_commit_id', 'path', 'ref', 'file_blob_sha', 'content', 'content_encoding', 'commit_sha', 'commit_message', 'author_user_id', 'source_branch', 'target_branch', 'title', 'description', 'reviewer_user_ids', 'work_item_ids', 'change_request_id', 'comment_body', 'patch_set_number', 'diff_summary', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted', 'open', 'merged', 'closed']
  - constraint: organization_id IS NOT NULL
  - constraint: repository_id IS NOT NULL WHERE entity_type IN ('branch','file','commit','change_request','change_request_comment','patch_set')
  - constraint: unique(repository_id, branch_name) WHERE entity_type='branch' AND status!='deleted'
  - constraint: unique(repository_id, path, ref) WHERE entity_type='file' AND status!='deleted'
- `projects.json` — Project management entities: projects and work items. Supports project search and work item retrieval/search. (28 rows; fields: ['id', 'entity_type', 'status', 'organization_id', 'project_id', 'name', 'key', 'description', 'work_item_type', 'assignee_user_id', 'reporter_user_id', 'priority', 'labels', 'sprint', 'due_date', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted', 'open', 'in_progress', 'resolved', 'closed', 'cancelled']
  - constraint: organization_id IS NOT NULL
  - constraint: unique(organization_id, key) WHERE entity_type='project' AND key IS NOT NULL AND status!='deleted'
  - constraint: project_id IS NOT NULL WHERE entity_type='work_item'
  - constraint: priority BETWEEN 1 AND 5 WHERE entity_type='work_item' AND priority IS NOT NULL
- `pipelines.json` — Pipeline definitions, pipeline runs, job templates, job run instances, execution history, and logs. Covers listing/searching pipelines, starting runs, inspecting runs, listing jobs by category, running a job, and retrieving logs. (31 rows; fields: ['id', 'entity_type', 'status', 'organization_id', 'pipeline_id', 'pipeline_run_id', 'pipeline_job_id', 'name', 'category', 'definition', 'run_number', 'triggered_by_user_id', 'parameters', 'started_at', 'finished_at', 'duration_seconds', 'log_uri', 'log_content', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted', 'queued', 'running', 'succeeded', 'failed', 'canceled', 'skipped']
  - constraint: organization_id IS NOT NULL
  - constraint: unique(organization_id, name) WHERE entity_type='pipeline' AND status!='deleted'
  - constraint: pipeline_id IS NOT NULL WHERE entity_type IN ('pipeline_run','pipeline_job')
  - constraint: pipeline_run_id IS NOT NULL WHERE entity_type IN ('pipeline_job_run','pipeline_job_log')
- `packages.json` — Packages management: package repositories and artifacts stored under an organization. Supports listing package repos, listing artifacts, and retrieving a single artifact. (18 rows; fields: ['id', 'entity_type', 'status', 'organization_id', 'package_repository_id', 'name', 'repo_type', 'format', 'version', 'checksum_sha256', 'size_bytes', 'download_url', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: organization_id IS NOT NULL
  - constraint: unique(organization_id, name, repo_type) WHERE entity_type='package_repository' AND status!='deleted'
  - constraint: package_repository_id IS NOT NULL WHERE entity_type='artifact'
  - constraint: unique(package_repository_id, name, version) WHERE entity_type='artifact' AND status!='deleted'

## Business rules enforced by the tools

- Every request is authorized by an active api_token (identity.entity_type='api_token' AND status='active'); the token must map to exactly one user_id and one organization_id.
- get_current_user returns the identity row with entity_type='user' matching the authorized token's user_id.
- get_current_organization_info returns the organization from the authorized token's organization_id unless an explicit organization is provided by the upstream adapter; if multiple orgs are available, token org takes precedence.
- get_user_organizations returns all organizations where a membership row exists with membership.user_id = token.user_id AND membership.status='active'.
- list_repositories returns codeup rows with entity_type='repository' filtered by organization_id; get_repository returns exactly one such row by id and organization_id.
- create_branch inserts a codeup row entity_type='branch' with unique(repository_id, branch_name) among non-deleted branches; it must set head_commit_id to the source ref's commit when available.
- delete_branch performs a soft delete by setting status='deleted' for the branch row; hard deletion is disallowed to preserve auditability.
- get_file_blobs reads codeup file row by (repository_id, path, ref) and returns content; if content is not stored inline, it must be retrievable via blob SHA from the upstream git store referenced by file_blob_sha.
- create_file creates/updates a codeup file row for (repository_id, path, ref=branch) and records a commit row with commit_sha; update_file requires the file exists at the given path/ref and creates a new commit row; delete_file marks the file row status='deleted' at that ref and creates a commit row.
- compare must compute diff_summary between two refs within the same repository; if persisted, it is stored on a patch_set row or transiently computed without violating FK constraints.
- create_change_request inserts a codeup row entity_type='change_request' with status='open' and required fields (repository_id, source_branch, target_branch, organization_id); reviewer_user_ids must reference user identity IDs belonging to the same organization via active membership.
- create_change_request_comment inserts a codeup row entity_type='change_request_comment' linked by change_request_id; the parent change request must exist and have status in ('open','closed','merged') but not 'deleted'.
- list_change_request_patch_sets returns codeup rows entity_type='patch_set' for the change_request_id ordered by patch_set_number ascending; patch_set_number must be contiguous per change request (no gaps) unless imported from upstream.
- search_projects returns projects rows entity_type='project' filtered by organization_id and text match on name/key/description; archived projects are included only if explicitly requested by adapter defaults.
- get_project returns a single project row (entity_type='project') by id and organization_id; get_work_item returns a single work_item row by id and organization_id.
- search_workitems filters work_item rows by organization_id plus optional fields (project_id, status, assignee_user_id, labels, sprint, due_date ranges) implemented by querying projects collection fields.
- list_pipelines returns pipelines rows entity_type='pipeline' for an organization with optional status filtering; smart_list_pipelines additionally applies a time window filter by interpreting natural language into started_at/created_at ranges over pipeline_run rows joined to pipelines.
- create_pipeline_run inserts a pipelines row entity_type='pipeline_run' with status='queued', assigns run_number = max(run_number)+1 per pipeline_id, and records triggered_by_user_id from the token user.
- get_latest_pipeline_run returns the pipeline_run row with the highest run_number for a given pipeline_id (or latest created_at if run_number missing).
- list_pipeline_runs returns pipeline_run rows filtered by organization_id, pipeline_id, status, and started_at/created_at ranges.
- list_pipeline_jobs_by_category returns pipeline_job rows for a pipeline_id filtered by category; for this MCP surface, category='DEPLOY' must be supported and validated.
- execute_pipeline_job_run inserts a pipeline_job_run row with status='queued' linked to an existing pipeline_run and pipeline_job; it is disallowed if the parent pipeline_run status is in ('succeeded','failed','canceled').
- list_pipeline_job_historys returns pipeline_job_run rows for a given pipeline_job_id ordered by created_at desc; it must only return runs under the same organization_id.
- get_pipeline_job_run_log returns the newest pipeline_job_log row for a given pipeline_job_run; if log_content is truncated, log_uri must be present.
- list_package_repositories returns packages rows entity_type='package_repository' filtered by organization_id and optional repo_type/name search.
- list_artifacts returns packages rows entity_type='artifact' filtered by package_repository_id, optional name/version filtering, and status='active' unless explicitly requested.
- get_artifact returns a single artifact by id with FK package_repository_id existing and belonging to the same organization_id.
- All collections enforce updated_at >= created_at and soft deletion semantics via status='deleted' for user-facing deletes.