# Railway MCP Server — local MCP environment

This backend models a Railway account's projects and the resources inside them: environments, services, deployments, domains/TCP endpoints, volumes, and environment variables. Primary workflows include creating/deleting projects, provisioning services (from repo/image or database templates), triggering and inspecting deployments (status/logs), and managing connectivity (domains/TCP proxies), storage (volumes), and configuration (variables).

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@mh8974/railway-mcp

## Datastore

- `projects.json` — Railway projects (top-level container) with their environments and services. (18 rows; fields: ['id', 'account_id', 'name', 'description', 'status', 'default_environment_id', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'deleting', 'deleted']
  - constraint: unique(account_id, name) WHERE deleted_at IS NULL
  - constraint: status='deleted' implies deleted_at IS NOT NULL
- `environments.json` — Environments within a project (e.g., production, staging) that scope deployments, variables, domains, and TCP proxies. (18 rows; fields: ['id', 'project_id', 'name', 'slug', 'is_default', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(project_id, slug)
  - constraint: unique(project_id) WHERE is_default = true
  - constraint: slug matches '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'
- `services.json` — Deployable services within a project. Includes app services (repo/image) and database services (template-based), plus attached configuration (variables, domains, tcp proxies, volumes) via environment-scoped records. (18 rows; fields: ['id', 'project_id', 'name', 'service_type', 'source', 'status', 'deleted_at', 'last_deployment_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'paused', 'deleting', 'deleted']
  - constraint: unique(project_id, name) WHERE deleted_at IS NULL
  - constraint: service_type='app_repo' implies source.provider IS NOT NULL AND source.repo IS NOT NULL
  - constraint: service_type='app_image' implies source.image IS NOT NULL
  - constraint: service_type='database_template' implies source.template_slug IS NOT NULL AND source.engine IS NOT NULL
- `deployments.json` — Deployments of a service into a specific environment, including status and logs. (18 rows; fields: ['id', 'service_id', 'environment_id', 'triggered_by', 'trigger_context', 'status', 'started_at', 'finished_at', 'logs_text', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'building', 'deploying', 'success', 'failed', 'cancelled']
  - constraint: foreign key (service_id) references services(id) on delete restrict
  - constraint: foreign key (environment_id) references environments(id) on delete restrict
  - constraint: finished_at IS NULL OR finished_at >= started_at
  - constraint: status IN ('success','failed','cancelled') implies finished_at IS NOT NULL
- `service_environment_resources.json` — Environment-scoped resources attached to a service: domains, TCP proxies, volumes, and environment variables. Collapses multiple child tables into one polymorphic collection to stay within the 3-6 collection limit while still mapping all tools. (18 rows; fields: ['id', 'service_id', 'environment_id', 'resource_type', 'status', 'name', 'spec', 'checksum', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'provisioning', 'failed', 'deleting', 'deleted']
  - constraint: foreign key (service_id) references services(id) on delete restrict
  - constraint: foreign key (environment_id) references environments(id) on delete restrict
  - constraint: status='deleted' implies deleted_at IS NOT NULL
  - constraint: resource_type='variable' implies spec.key IS NOT NULL AND spec.value IS NOT NULL
- `api_tokens.json` — Stored authentication configuration for the MCP server (mapped to configure_api_token). In real deployments tokens are often only in secrets storage, but the server may persist a reference and validation metadata. (18 rows; fields: ['id', 'account_id', 'provider', 'token_ciphertext', 'token_last4', 'status', 'validated_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'invalid']
  - constraint: unique(account_id, provider) WHERE status='active'
  - constraint: length(token_last4) = 4

## Business rules enforced by the tools

- project_list returns projects where account_id matches the authenticated api_tokens.account_id and projects.status != 'deleted'.
- project_info returns a single project plus derived data: list of environments (environments.project_id=projects.id) and services (services.project_id=projects.id).
- project_create inserts a projects row (status='active') and MUST also create at least one environments row; exactly one environment per project MUST have is_default=true, and projects.default_environment_id must reference it.
- project_delete transitions projects.status from active->deleting->deleted and MUST soft-delete or hard-delete dependent services and their resources; once deleted, no new environments/services/resources may be created for that project.
- project_environments lists environments for a project_id and excludes archived only if the API tool requests it (default is all).
- service_list lists services by project_id where services.status != 'deleted'.
- service_info returns the service plus its last deployment per environment (max(deployments.created_at) grouped by environment_id) and attached resources in service_environment_resources.
- service_create_from_repo creates a services row with service_type='app_repo' and source containing repo metadata; it MUST also create an initial deployments row in the project's default environment with status='queued'.
- service_create_from_image creates a services row with service_type='app_image' and source containing image metadata; it MUST also create an initial deployments row in the project's default environment with status='queued'.
- database_list_types is served from an internal allowlist of templates and engines; when materialized, it corresponds to services.service_type='database_template' and services.source.engine/template_slug values that are permitted.
- database_deploy_from_template creates a services row with service_type='database_template' and MUST create at least one volume resource (resource_type='volume') in the target environment if the template requires persistence.
- deployment_list lists deployments filtered by (service_id, environment_id) ordered by created_at desc.
- deployment_trigger creates a new deployments row for the given (service_id, environment_id) with status='queued' and triggered_by='api'; it MUST be rejected if services.status in ('deleting','deleted').
- deployment_status reads deployments.status and timestamps; a deployment can only move forward via the declared transitions and cannot leave a terminal status (success/failed/cancelled).
- deployment_logs reads deployments.logs_text; logs must not be returned for deployments outside the authenticated account's projects.
- domain_check validates that the requested hostname is not already used by any non-deleted service_environment_resources row where resource_type='domain' and spec.hostname matches (case-insensitive).
- domain_create inserts a service_environment_resources row with resource_type='domain' and status='provisioning' or 'active'; it MUST enforce spec.target_port 1..65535 and hostname uniqueness.
- domain_update updates only allowed fields in spec for resource_type='domain' (e.g., target_port, tls_mode) and MUST NOT allow changing spec.hostname; attempting to do so must error.
- domain_delete transitions the matching domain resource to deleting->deleted and sets deleted_at.
- tcp_proxy_list returns service_environment_resources where resource_type='tcp_proxy' for a given service/environment.
- tcp_proxy_create inserts a tcp_proxy resource and MUST enforce uniqueness of spec.external_port per service/environment (no duplicates).
- tcp_proxy_delete transitions the tcp_proxy resource to deleting->deleted; if it is provisioning it may go directly to deleting.
- list_service_variables returns resources where resource_type='variable' for a given service/environment; values marked spec.is_secret=true must be masked unless the upstream Railway API returns plaintext.
- variable_set upserts a variable resource by (service_id, environment_id, spec.key); it updates spec.value and updated_at and should update checksum for idempotency.
- variable_bulk_set performs variable_set semantics for each entry and MUST be atomic per environment (all succeed or none) to prevent partial configuration.
- variable_delete soft-deletes the variable resource; deleting a non-existent key is a no-op only if the tool defines it so, otherwise error.
- variable_copy copies all non-deleted variable resources from a source environment to a target environment for the same service, overwriting keys that exist in the target (upsert).
- volume_list returns resources where resource_type='volume' across all services in a project by joining services.project_id and environments.project_id; only non-deleted volumes are returned.
- volume_create inserts a volume resource; it MUST validate spec.size_gb >= 1 and mount_path uniqueness per service/environment.
- volume_update updates allowed fields (e.g. size_gb increase); size_gb decreases must be rejected unless the underlying provider supports it.
- volume_delete transitions a volume resource to deleting->deleted; deletion must be rejected if a deployment is currently in building/deploying for the same service/environment unless forced by provider policy.
- configure_api_token upserts an api_tokens row for (account_id, provider='railway') and sets status='active' only after successful validation; invalid tokens must be stored with status='invalid' and validated_at set.