# n8n Workflow Integration Server — local MCP environment

This backend models an n8n instance manager that can provision/connect to an n8n server and then perform CRUD operations over core n8n entities: workflows, projects, users, variables, credentials, executions, and tags. The primary workflows are: initialize an instance connection, manage workflows (including activation and tagging), manage enterprise objects (projects/variables), manage users/credentials, inspect/delete execution history, and generate security audits.

Repository: https://github.com/tecnologiacomigo/n8n-mcp-server
Homepage: https://smithery.ai/server/@tecnologiacomigo/n8n-mcp-server

## Datastore

- `n8n_instances.json` — Registered n8n instances reachable by this MCP server. Created/ensured by init-n8n and used as the scope for all subsequent list/get/create/update/delete operations. (12 rows; fields: ['id', 'display_name', 'base_url', 'api_key_hash', 'auth_type', 'enterprise_features', 'last_healthcheck_at', 'last_healthcheck_status', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['provisioning', 'active', 'disabled', 'deleted']
  - constraint: unique(base_url)
  - constraint: auth_type in ('api_key','basic','oauth2','none')
  - constraint: status in ('provisioning','active','disabled','deleted')
  - constraint: last_healthcheck_status is null OR last_healthcheck_status in ('ok','degraded','down')
- `n8n_principals.json` — Users in the n8n instance (and optionally service principals). Supports list-users, create-users, get-user, delete-user and permission checks for owner-only operations. (25 rows; fields: ['id', 'instance_id', 'principal_type', 'email', 'first_name', 'last_name', 'role', 'is_owner', 'status', 'last_login_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['invited', 'active', 'suspended', 'deleted']
  - constraint: foreign key (instance_id) references n8n_instances(id) on delete cascade
  - constraint: unique(instance_id, email) where email is not null
  - constraint: role in ('owner','admin','member','viewer')
  - constraint: is_owner = (role = 'owner')
- `n8n_projects.json` — Enterprise project containers for workflows and assets. Supports list-projects, create-project, update-project, delete-project. (12 rows; fields: ['id', 'instance_id', 'name', 'description', 'created_by_principal_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: foreign key (instance_id) references n8n_instances(id) on delete cascade
  - constraint: unique(instance_id, name)
  - constraint: status in ('active','archived','deleted')
  - constraint: create/update/delete only allowed if n8n_instances.enterprise_features.projects_enabled = true
- `n8n_workflows.json` — Workflows and their full JSON definition (nodes + connections), activation state, and optional project assignment. Supports list-workflows, get-workflow, create-workflow, update-workflow, delete-workflow, activate-workflow, deactivate-workflow. (35 rows; fields: ['id', 'instance_id', 'project_id', 'name', 'definition', 'settings', 'active', 'status', 'created_by_principal_id', 'updated_by_principal_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'active', 'inactive', 'deleted']
  - constraint: foreign key (instance_id) references n8n_instances(id) on delete cascade
  - constraint: foreign key (project_id) references n8n_projects(id) on delete set null
  - constraint: unique(instance_id, name) where status != 'deleted'
  - constraint: definition must contain keys 'nodes' (array) and 'connections' (object)
- `n8n_assets_and_audit.json` — Consolidated storage for instance-scoped assets and logs that are manipulated by tools: variables, credentials, executions, tags, workflow-tag relations, and generated audits. Implemented as a polymorphic collection to stay within the 3-6 collection limit while still mapping every tool to persisted data. (31 rows; fields: ['id', 'instance_id', 'asset_type', 'external_id', 'workflow_id', 'project_id', 'owner_principal_id', 'name', 'key', 'value_encrypted', 'credential_type', 'data_encrypted', 'schema', 'execution_status', 'started_at', 'stopped_at', 'execution_data', 'tag_id', 'report', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: foreign key (instance_id) references n8n_instances(id) on delete cascade
  - constraint: foreign key (workflow_id) references n8n_workflows(id) on delete cascade
  - constraint: foreign key (project_id) references n8n_projects(id) on delete set null
  - constraint: foreign key (owner_principal_id) references n8n_principals(id) on delete set null

## Business rules enforced by the tools

- init-n8n must create or upsert exactly one n8n_instances row per base_url; on success it sets status='active' and last_healthcheck_status='ok'.
- All tools except init-n8n must reject requests if there is no n8n_instances row in status='active' for the selected/implicit instance scope.
- list-workflows returns n8n_workflows where instance_id matches and status != 'deleted'.
- get-workflow requires a workflow id; it returns the matching n8n_workflows row (including definition/settings) where status != 'deleted'.
- create-workflow must persist definition with required keys: nodes (array) and connections (object); it must not accept client-provided 'active' and must initialize status to 'inactive' (active=false) unless explicitly activated via activate-workflow.
- update-workflow must update name/definition/settings and updated_by_principal_id; it must not directly toggle active; activation changes only through activate-workflow/deactivate-workflow.
- delete-workflow transitions n8n_workflows.status to 'deleted' and must cascade-delete workflow_tag assets and mark related execution assets as execution_status='deleted' or status='deleted'.
- activate-workflow transitions n8n_workflows.status to 'active' and sets active=true; deactivate-workflow transitions to 'inactive' and sets active=false; transitions must follow the declared lifecycle graph.
- list-projects/create-project/update-project/delete-project must be rejected unless n8n_instances.enterprise_features.projects_enabled=true for the instance.
- delete-project must either (a) reject if any non-deleted workflows reference project_id, or (b) set those workflows.project_id to null; the backend enforces one consistent policy (default: reject).
- list-users is only permitted for a caller principal with role='owner' on that instance.
- create-users creates n8n_principals rows with status='invited' or 'active' according to instance policy; (instance_id,email) must be unique.
- get-user must support lookup by either id or email; when both are provided, id takes precedence and must match the email if the email exists.
- delete-user sets n8n_principals.status='deleted' and must not allow deleting the last remaining owner in an instance.
- list-variables/create-variable/delete-variable must be rejected unless n8n_instances.enterprise_features.variables_enabled=true.
- create-variable enforces uniqueness on (instance_id,key) among non-deleted variables and stores value only in encrypted form (value_encrypted).
- create-credential must store credential data only encrypted (data_encrypted) and record owner_principal_id; delete-credential requires the caller to match owner_principal_id or have role in ('owner','admin') per instance policy.
- get-credential-schema upserts/returns an asset_type='credential_schema' row keyed by (instance_id, credential_type).
- list-executions returns asset_type='execution' filtered by optional workflow_id and/or execution_status where status != 'deleted'.
- get-execution returns one execution asset by external_id (or id) and instance_id; delete-execution sets execution_status='deleted' and status='deleted'.
- create-tag/list-tags/get-tag/update-tag/delete-tag operate on asset_type='tag'; tag names must be unique per instance among non-deleted tags.
- get-workflow-tags returns all tags joined through asset_type='workflow_tag' rows for the given workflow_id; update-workflow-tags replaces the set atomically (delete removed relations, add new ones), enforcing (workflow_id, tag_id) uniqueness.
- generate-audit creates a new asset_type='audit_report' row with report JSON; only principals with role in ('owner','admin') may generate audits; audit reports must be immutable after creation except for status transitions.