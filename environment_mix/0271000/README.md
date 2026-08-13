# Railway MCP Server — local MCP environment

This backend models a Railway account’s projects and the resources inside them (environments, services, deployments, and operational configuration like variables, domains, TCP proxies, and volumes). Primary workflows include creating/deleting projects and services, triggering and monitoring deployments (status + logs), and managing service connectivity/configuration (domains, TCP proxies, and environment variables), plus deploying from templates and tracking template workflow status.

Repository: https://github.com/jason-tan-swe/railway-mcp
Homepage: https://smithery.ai/server/@jason-tan-swe/railway-mcp

## Datastore

- `railway_accounts.json` — Represents a configured Railway account context for the MCP server, including stored API token configuration and basic tenancy boundaries for all other objects. (12 rows; fields: ['id', 'display_name', 'api_token_ciphertext', 'api_token_last4', 'token_status', 'created_at', 'updated_at'])
  - lifecycle `token_status`: ['unset', 'active', 'revoked']
  - constraint: unique(display_name)
  - constraint: token_status = 'unset' implies api_token_ciphertext IS NULL
  - constraint: token_status = 'active' implies api_token_ciphertext IS NOT NULL
- `projects.json` — Railway projects and their environments, used by project_list/project_info/project_create/project_delete and as the parent for services, volumes, etc. Environments are stored inline because the tool surface treats environments primarily as listable metadata under a project. (21 rows; fields: ['id', 'account_id', 'railway_project_id', 'name', 'description', 'status', 'environments', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleting', 'deleted']
  - constraint: unique(account_id, railway_project_id)
  - constraint: unique(account_id, name)
  - constraint: environments is non-empty for status='active' after first successful project_info sync
- `services.json` — Services within projects, including build source (repo/image/template/database), operational endpoints (domains, tcp proxies), configuration (variables), persistent storage (volumes), and deployments. Serves service_list/service_info/service_create_from_repo/service_create_from_image/service_update/service_delete/service_restart and is the anchor for domain/tcp/variable/volume and deployments. (42 rows; fields: ['id', 'project_id', 'railway_service_id', 'name', 'service_type', 'source', 'status', 'config', 'domains', 'tcp_proxies', 'variables', 'volumes', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'restarting', 'deleting', 'deleted']
  - constraint: unique(project_id, railway_service_id)
  - constraint: unique(project_id, name)
  - constraint: service_type='repo' implies source.repo_url IS NOT NULL
  - constraint: service_type='image' implies source.image IS NOT NULL
- `deployments.json` — Deployment history per service/environment, including status and logs. Supports deployment_list, deployment_trigger, deployment_status, deployment_logs, and deployment_wait-like polling patterns. (40 rows; fields: ['id', 'service_id', 'railway_environment_id', 'railway_deployment_id', 'trigger_reason', 'commit_sha', 'image_digest', 'status', 'started_at', 'finished_at', 'logs', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'building', 'deploying', 'succeeded', 'failed', 'cancelled']
  - constraint: unique(service_id, railway_deployment_id)
  - constraint: finished_at IS NULL for status in ('queued','building','deploying')
  - constraint: finished_at IS NOT NULL for status in ('succeeded','failed','cancelled')
  - constraint: logs entries are append-only (no mutation; only add)
- `templates_and_db_types.json` — Catalog data for database types and templates, plus template deploy workflows. Supports database_list_types, template_list, template_deploy, and template_get_workflow_status. (12 rows; fields: ['id', 'account_id', 'database_types', 'templates', 'template_workflows', 'created_at', 'updated_at'])
  - lifecycle `template_workflows[].status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: unique(account_id) for the latest active catalog snapshot (enforced by a single-row-per-account policy)
  - constraint: for templates array: unique(railway_template_id) within snapshot
  - constraint: for database_types array: unique(railway_db_type_id) within snapshot
  - constraint: for template_workflows array: unique(railway_workflow_id) within snapshot

## Business rules enforced by the tools

- configure_api_token must upsert railway_accounts.api_token_ciphertext and set token_status='active'; it must not store plaintext tokens.
- project_list returns all projects where projects.account_id matches the active Railway account and projects.status != 'deleted'.
- project_delete transitions projects.status from 'active' -> 'deleting' immediately, and to 'deleted' only after upstream deletion is confirmed; services under the project must also be transitioned to 'deleting'/'deleted' accordingly.
- service_list returns services scoped to a selected project; service_info requires the service belongs to the given project_id (FK integrity enforced).
- service_create_from_repo/service_create_from_image/template_deploy/database_deploy (implied by database_list_types) must create a services row with correct service_type and required source fields, and must store the upstream railway_service_id once obtained.
- service_delete must transition services.status from 'active'/'restarting' -> 'deleting' and finally 'deleted'; deleted services are immutable (no updates, domains/variables/tcp/volumes changes rejected).
- service_restart sets services.status to 'restarting' and creates a new deployments row only if the upstream platform records a deployment/restart event; status must revert to 'active' after confirmation.
- deployment_trigger must create a deployments row in status='queued' and enforce at most 1 active deployment per (service_id, railway_environment_id) in statuses ('queued','building','deploying').
- deployment_status may only advance according to the deployments.status transition graph; it must not move from terminal states ('succeeded','failed','cancelled') back to non-terminal.
- deployment_logs appends to deployments.logs; it must never delete or reorder existing log entries (append-only constraint).
- domain_check must reject domains that already exist in any services.domains[*].hostname for the same account (global uniqueness within account).
- domain_update may change configuration fields (e.g., target_port, tls settings) but must not change the hostname; hostname changes require domain_delete + domain_create.
- tcp_proxy_create must enforce that (service, environment, external_port) is unique and that external_port is between 1 and 65535; tcp_proxy_delete must remove exactly one proxy mapping.
- list_service_variables returns variables filtered by service and environment; variable_set upserts a key within that environment; variable_delete removes that key; variable_bulk_set performs multiple upserts atomically per environment.
- variable_copy copies variables from one environment to another within the same service, refusing to overwrite keys unless explicitly allowed by the workflow implementation (default: overwrite).
- volume_create must enforce size_gb range [1, 10240] and unique mount_path per (service, environment); volume_delete must be blocked if the volume status indicates attachment/migration in progress (e.g., 'provisioning'/'resizing') as reflected in services.volumes[*].status.
- template_get_workflow_status must look up a workflow execution by railway_workflow_id in catalog.template_workflows and return its current status; if status is terminal, output_service_railway_ids must be present for succeeded workflows.