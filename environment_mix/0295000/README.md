# n8n Workflow Integration Server — local MCP environment

This backend models an n8n instance exposed through an integration server: it stores workflows (including their node graph JSON), executions, tags and tag assignments, plus administrative entities (users, projects, variables, credentials) required by the tool surface. The main workflows are: provisioning/initializing an instance connection, CRUD on workflows/projects/users/variables/credentials/tags, managing workflow activation and tag assignments, and querying/deleting execution history and generating audit reports.

Repository: https://github.com/guinness77/n8n-mcp-server
Homepage: https://smithery.ai/server/@guinness77/n8n-mcp-server

## Datastore

- `instances.json` — Represents a connected n8n deployment that this MCP server can manage (base URL, auth, license capabilities, and operational state). Used by init-n8n and to scope all subsequent reads/writes. (12 rows; fields: ['id', 'display_name', 'base_url', 'auth_type', 'auth_secret_ref', 'cap_projects_enabled', 'cap_variables_enabled', 'cap_audit_enabled', 'owner_user_id', 'status', 'last_healthcheck_at', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['provisioning', 'ready', 'error', 'disabled']
  - constraint: unique(base_url)
  - constraint: display_name != ''
  - constraint: base_url must be a valid URL
  - constraint: auth_type != 'none' implies auth_secret_ref is not null
- `users.json` — Users in an n8n instance. Supports list-users, create-users, get-user, delete-user and ownership checks for credentials. (30 rows; fields: ['id', 'instance_id', 'n8n_user_id', 'email', 'first_name', 'last_name', 'role', 'status', 'last_login_at', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['invited', 'active', 'disabled', 'deleted']
  - constraint: unique(lower(email), instance_id)
  - constraint: email must be a valid email
  - constraint: deleted_at is not null implies status='deleted'
- `projects.json` — Enterprise project containers in n8n used to group workflows/resources. Supports list-projects, create-project, update-project, delete-project. (12 rows; fields: ['id', 'instance_id', 'n8n_project_id', 'name', 'status', 'created_by_user_id', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: instances.cap_projects_enabled must be true to create/update/delete
  - constraint: unique(name, instance_id) where status='active'
  - constraint: deleted_at is not null implies status='deleted'
- `workflows.json` — n8n workflows including full node graph JSON, activation state, and project association. Supports list-workflows, get-workflow, create-workflow, update-workflow, delete-workflow, activate-workflow, deactivate-workflow. (17 rows; fields: ['id', 'instance_id', 'project_id', 'n8n_workflow_id', 'name', 'status', 'active', 'nodes', 'connections', 'settings', 'static_data', 'version_id', 'created_by_user_id', 'updated_by_user_id', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['draft', 'active', 'inactive', 'deleted']
  - constraint: nodes is required and must be an array (can be empty)
  - constraint: connections is required and must be an object (can be empty)
  - constraint: active = (status='active') (derived/maintained invariant)
  - constraint: unique(name, instance_id) where status!='deleted'
- `ops_and_metadata.json` — Operational and metadata entities grouped into one physical collection for a small-footprint integration server: executions, tags & workflow-tag mappings, variables, credentials, credential schemas, and audit reports. This single collection is partitioned by record_type and indexed per subtype. (33 rows; fields: ['id', 'instance_id', 'record_type', 'status', 'ref_id', 'workflow_id', 'tag_id', 'project_id', 'user_id', 'name', 'type_name', 'data', 'started_at', 'finished_at', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'active', 'inactive', 'deleted']
  - constraint: record_type='execution' implies workflow_id is not null
  - constraint: record_type='workflow_tag' implies workflow_id is not null and tag_id is not null
  - constraint: record_type='tag' implies name is not null
  - constraint: record_type='variable' implies name is not null and instances.cap_variables_enabled=true for create/delete

## Business rules enforced by the tools

- init-n8n creates or updates exactly one instances row per base_url; if connectivity/auth validation fails, instances.status must be set to 'error' and last_error populated.
- All tools must be scoped to a single ready instance; operations must reject when instances.status != 'ready' (except init-n8n).
- create-workflow must reject payloads that include an 'active' property; status is initialized to 'inactive' unless explicitly activated via activate-workflow.
- activate-workflow may only transition workflows.status from 'draft' or 'inactive' to 'active'; deactivate-workflow may only transition from 'active' to 'inactive'.
- delete-workflow, delete-user, delete-project, delete-variable, delete-credential, delete-tag, delete-execution must be idempotent: if already deleted, the operation succeeds without changing non-audit fields.
- list-workflows/get-workflow must not return rows with status='deleted' unless an internal flag is used (not exposed by tool surface).
- Workflow tag updates: update-workflow-tags replaces the full set of mappings for a workflow (ops_and_metadata record_type='workflow_tag'); the resulting set must be unique per (workflow_id, tag_id).
- get-workflow-tags returns tags by joining workflows.id to workflow_tag mappings (workflow_id) and then to tag records (tag_id), excluding deleted tags/mappings.
- create-tag must enforce unique tag name per instance (case-insensitive); update-tag may rename but cannot collide with another active tag name.
- create-variable and delete-variable must enforce instances.cap_variables_enabled=true; otherwise return a license/capability error.
- list-projects/create-project/update-project/delete-project must enforce instances.cap_projects_enabled=true; otherwise return a license/capability error.
- generate-audit must enforce instances.cap_audit_enabled=true; it creates an audit_report record with status 'queued' then transitions through running to succeeded/failed; it must persist the generated report payload in data (with secrets redacted).
- create-credential must verify the provided type_name exists as a credential_schema for the instance; if absent, get-credential-schema should be called and cached as a credential_schema record.
- delete-credential must verify the caller user owns the credential (ops_and_metadata.user_id) or is instance owner; otherwise reject.
- list-executions/get-execution must only return executions for workflows in the same instance and exclude deleted executions by default.
- delete-project must be blocked when the project still has non-deleted workflows referencing it, unless a cascading delete is explicitly implemented (not exposed by tool surface).
- Foreign keys must be enforced: workflows.instance_id, projects.instance_id, users.instance_id, and ops_and_metadata.instance_id must reference an existing instances.id; ops_and_metadata.workflow_id must reference workflows.id when record_type requires it.