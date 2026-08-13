# n8n Assistant — local MCP environment

This backend stores metadata about an n8n Assistant deployment and the n8n instance(s) it can describe. The primary workflow is read-only: clients call get_n8n_info to retrieve the current deployment/instance information, versioning, and health/status details; operators can update the stored config/status via internal processes.

Repository: https://github.com/onurpolat05/n8n-Assistant
Homepage: https://smithery.ai/server/@onurpolat05/n8n-assistant

## Datastore

- `deployments.json` — Represents a single running n8n Assistant deployment (environment) that serves API requests. This is the canonical row read by get_n8n_info to present service identity and runtime details. (12 rows; fields: ['id', 'public_name', 'repository_url', 'environment', 'service_base_url', 'version', 'git_commit', 'build_time', 'status', 'last_healthcheck_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['starting', 'ready', 'degraded', 'maintenance', 'offline']
  - constraint: unique(environment)
  - constraint: public_name <> ''
  - constraint: repository_url LIKE 'http%'
  - constraint: version <> ''
- `n8n_instances.json` — Represents an n8n server/instance that the assistant can describe. Stored separately to support multiple n8n targets per deployment. (12 rows; fields: ['id', 'deployment_id', 'name', 'base_url', 'n8n_version', 'auth_type', 'is_primary', 'status', 'last_checked_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['unknown', 'reachable', 'unreachable', 'disabled']
  - constraint: foreign_key(deployment_id) references deployments(id) on delete cascade
  - constraint: unique(deployment_id, name)
  - constraint: unique(deployment_id, base_url)
  - constraint: base_url LIKE 'http%'
- `service_capabilities.json` — Declarative capabilities and categories/tags exposed by the deployment for inclusion in get_n8n_info results. (12 rows; fields: ['id', 'deployment_id', 'categories', 'tags', 'tool_names', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: foreign_key(deployment_id) references deployments(id) on delete cascade
  - constraint: unique(deployment_id)
  - constraint: array_length(tool_names) >= 1
  - constraint: tool_names contains 'get_n8n_info'
- `info_requests.json` — Audit log of get_n8n_info calls. Enables operational metrics, debugging, and abuse detection even though the tool itself takes no parameters. (19 rows; fields: ['id', 'deployment_id', 'requested_at', 'request_ip', 'user_agent', 'response_status_code', 'latency_ms', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['success', 'error', 'throttled']
  - constraint: foreign_key(deployment_id) references deployments(id) on delete cascade
  - constraint: response_status_code between 100 and 599
  - constraint: latency_ms >= 0 and latency_ms <= 600000

## Business rules enforced by the tools

- get_n8n_info MUST select exactly one deployments row for the current environment and return its public_name, repository_url, environment, version, and status.
- get_n8n_info MUST include the active service_capabilities row for the deployment; if none is active, the endpoint MUST still succeed but return empty categories/tags/tool_names derived from defaults.
- Each deployment MUST have at most one service_capabilities row (enforced by unique(deployment_id)).
- Each deployment MUST have at most one n8n_instances row with is_primary = true; if multiple exist due to data corruption, get_n8n_info MUST deterministically pick the most recently updated primary instance.
- The system MUST log every get_n8n_info call into info_requests with requested_at, response_status_code, latency_ms, and outcome status.
- If the request rate from a single IP exceeds a configured threshold, new info_requests rows MUST be written with status='throttled' and response_status_code=429.
- Status transitions for deployments and n8n_instances MUST follow the declared lifecycle transition graphs; invalid transitions MUST be rejected at write time.