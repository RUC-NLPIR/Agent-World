# Oso Cloud MCP Server — local MCP environment

This backend stores Oso Cloud authorization configuration (workspaces, deployed policies) and runtime authorization data (actors, resources, relationships/facts) along with audit logs of authorization decisions. Primary workflows are: deploy and fetch the current policy, evaluate authorize decisions, enumerate accessible resources for an actor/action/type, and list allowed actions for an actor on a resource.

Repository: https://github.com/robinbortlik/oso-cloud-mcp/
Homepage: https://smithery.ai/server/@robinbortlik/oso-cloud-mcp

## Datastore

- `workspaces.json` — Tenant boundary for Oso Cloud usage, including API keys, policy deployment state, and quotas. (18 rows; fields: ['id', 'name', 'status', 'current_policy_id', 'default_decision', 'quota_authorize_per_minute', 'quota_list_per_minute', 'quota_actions_per_minute', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: quota_authorize_per_minute >= 0
  - constraint: quota_list_per_minute >= 0
  - constraint: quota_actions_per_minute >= 0
- `api_keys.json` — API keys used by clients (including the MCP server) to authenticate to a workspace; used for quota enforcement and request attribution. (19 rows; fields: ['id', 'workspace_id', 'name', 'key_prefix', 'key_hash', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(workspace_id, key_prefix)
  - constraint: workspace_id references workspaces.id (on delete cascade)
  - constraint: status in ('active','revoked')
- `policies.json` — Versioned policy documents deployed to a workspace; one policy may be active at a time. (18 rows; fields: ['id', 'workspace_id', 'version', 'polar_source', 'source_sha256', 'status', 'compiled_at', 'activated_at', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'deploying', 'active', 'superseded', 'failed']
  - constraint: unique(workspace_id, version)
  - constraint: unique(workspace_id, source_sha256)
  - constraint: workspace_id references workspaces.id (on delete cascade)
  - constraint: version >= 1
- `authz_tuples.json` — Relationship/fact tuples used by the authorization engine (actor-resource relations and attributes) to support authorize, list_resources, and get_actions. (18 rows; fields: ['id', 'workspace_id', 'subject_type', 'subject_id', 'relation', 'object_type', 'object_id', 'object_subrelation', 'status', 'valid_from', 'valid_to', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: workspace_id references workspaces.id (on delete cascade)
  - constraint: unique(workspace_id, subject_type, subject_id, relation, object_type, object_id, object_subrelation)
  - constraint: status in ('active','deleted')
  - constraint: valid_from is null or valid_to is null or valid_from < valid_to
- `authorization_checks.json` — Audit trail of authorization evaluations and query-style operations (authorize, list_resources, get_actions) for debugging, compliance, and rate limiting. (19 rows; fields: ['id', 'workspace_id', 'api_key_id', 'policy_id', 'tool', 'actor', 'action', 'resource', 'resource_type', 'result_allowed', 'result_resource_ids', 'result_actions', 'latency_ms', 'status', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['success', 'denied', 'error', 'rate_limited']
  - constraint: workspace_id references workspaces.id (on delete cascade)
  - constraint: api_key_id references api_keys.id (nullable, on delete set null)
  - constraint: policy_id references policies.id (nullable, on delete set null)
  - constraint: latency_ms >= 0

## Business rules enforced by the tools

- Every tool invocation is associated with exactly one workspace (resolved from the presented API key or server configuration) and must create one authorization_checks row.
- get_policy returns workspaces.current_policy_id; if null, it returns an empty/absent policy and records tool='get_policy' with status='success'.
- authorize evaluates against the workspace's current active policy; if no active policy exists, the decision must follow workspaces.default_decision and be logged accordingly.
- list_resources returns only resources of the requested resource_type for which authorize(actor, action, resource) would be allowed under the same policy snapshot; results may be truncated but must be consistent with the policy at evaluation time.
- get_actions returns the set of actions allowed for the (actor, resource) pair under the same policy snapshot; empty set is permitted and must be logged as success.
- Rate limiting: for each workspace and tool family, if the count of authorization_checks for that workspace within the last rolling minute exceeds the corresponding workspace quota, the request must be rejected with status='rate_limited' and an authorization_checks row must still be written.
- API keys with status='revoked' cannot be used; attempts must be logged with status='error' and error_code='api_key_revoked'.
- Only one policy per workspace may have status='active' at any time; activating a new policy must transition the previously active policy to 'superseded' and update workspaces.current_policy_id atomically.
- authz_tuples with status='deleted' must be ignored by all evaluations; validity windows (valid_from/valid_to) must be enforced when present.
- Foreign key integrity must hold for all workspace-scoped records; deleting a workspace cascades deletion of api_keys, policies, authz_tuples, and authorization_checks.