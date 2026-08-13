# CodeRide — local MCP environment

CodeRide stores deployable projects (identified by a 3-letter uppercase slug) and their tasks (identified by a human-facing number like 'CRD-1'). The main workflow is: start/deploy a project, retrieve project/task details and task prompts, and update task status/description plus update the project's knowledge graph and Mermaid diagram.

Repository: https://github.com/PixdataOrg/coderide-mcp
Homepage: https://smithery.ai/server/@PixdataOrg/coderide

## Datastore

- `projects.json` — Top-level project entity addressed by a 3-letter slug (e.g., 'CRD'). Stores knowledge graph content and an optional Mermaid structure diagram. (36 rows; fields: ['id', 'slug', 'name', 'description', 'project_knowledge', 'project_diagram', 'default_prompt', 'status', 'deployed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'deploying', 'active', 'paused', 'archived', 'error']
  - constraint: unique(slug)
  - constraint: slug matches regex ^[A-Z]{3}$
  - constraint: length(project_diagram) <= 200000 or project_diagram is null
- `tasks.json` — Work items within a project. Each task has a stable human-facing number like 'CRD-1' plus an internal numeric sequence within the project. (30 rows; fields: ['id', 'project_id', 'sequence_no', 'number', 'title', 'description', 'prompt', 'status', 'priority', 'created_at', 'updated_at', 'completed_at'])
  - lifecycle `status`: ['todo', 'in_progress', 'blocked', 'done', 'cancelled']
  - constraint: unique(project_id, sequence_no)
  - constraint: unique(number)
  - constraint: sequence_no >= 1
  - constraint: priority between 1 and 5
- `deployments.json` — Tracks project deployments/starts initiated via start_project; keeps audit of success/failure and where it was deployed. (33 rows; fields: ['id', 'project_id', 'status', 'environment', 'trigger', 'started_at', 'finished_at', 'endpoint_url', 'logs', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: finished_at is null when status in ('queued','running')
  - constraint: finished_at is not null when status in ('succeeded','failed','cancelled')
  - constraint: endpoint_url is not null when status='succeeded'
- `api_keys.json` — API keys used to call the service; supports rate limiting and auditing for updates/reads to projects/tasks. (31 rows; fields: ['id', 'key_prefix', 'key_hash', 'status', 'scopes', 'project_id', 'requests_per_minute_limit', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_prefix)
  - constraint: unique(key_hash)
  - constraint: requests_per_minute_limit between 1 and 6000
  - constraint: project_id is null or references projects.id
- `audit_events.json` — Immutable audit log of reads and mutations for projects/tasks, used for debugging and compliance (who changed what, when). (37 rows; fields: ['id', 'api_key_id', 'action', 'project_id', 'task_id', 'request_payload', 'response_status_code', 'source_ip', 'user_agent', 'created_at', 'updated_at'])
  - constraint: task_id is null or references tasks.id
  - constraint: project_id is null or references projects.id
  - constraint: if task_id is not null then project_id must equal tasks.project_id (enforced in application or via trigger)
  - constraint: response_status_code between 100 and 599

## Business rules enforced by the tools

- start_project creates a deployments row with status='queued' (or 'running') for a resolved project and transitions the project.status to 'deploying' unless it is 'archived'.
- If a deployment reaches status='succeeded', set projects.status='active' and projects.deployed_at=finished_at; if status='failed', set projects.status='error'.
- get_project resolves a project by projects.slug; slug must match ^[A-Z]{3}$.
- get_task resolves a task by tasks.number; tasks.number must be globally unique and must equal '{projects.slug}-{tasks.sequence_no}'.
- get_prompt returns tasks.prompt if non-null; otherwise returns projects.default_prompt. If both are null, return an empty string or a defined service default.
- update_task requires at least one of (description, status) to be provided; it updates tasks.updated_at and writes an audit_events row.
- update_task status changes must follow the tasks.lifecycle.transitions; if status changes to 'done', set completed_at=now; if status changes away from 'done' (disallowed by transitions), reject.
- update_project requires at least one of (project_knowledge, project_diagram) to be provided; it updates projects.updated_at and writes an audit_events row.
- project_diagram, when provided, must be valid UTF-8 text and must not exceed the configured max length (constraint listed).
- All tool calls should create an audit_events row capturing action, resolved project/task ids, response_status_code, and redacted request_payload.
- API keys with status='revoked' are rejected; requests are rate limited by api_keys.requests_per_minute_limit; if api_keys.project_id is set, access to other projects is forbidden.