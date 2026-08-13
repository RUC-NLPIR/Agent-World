# Multi Cluster Kubernetes Server — local MCP environment

This backend stores a registry of Kubernetes contexts (clusters) available to the server and an audited history of user-initiated operations executed against those contexts. Read tools primarily query live cluster state but can be cached for performance; mutating tools create operation records, validate authorization, enforce quotas, and persist results/errors for traceability.

Repository: https://github.com/razvanmacovei/k8s-multicluster-mcp
Homepage: https://smithery.ai/server/@razvanmacovei/k8s-multicluster-mcp

## Datastore

- `k8s_contexts.json` — Registered Kubernetes contexts derived from kubeconfig sources, used as the primary routing target for all cluster operations. (26 rows; fields: ['id', 'context_name', 'cluster_name', 'user_name', 'server', 'kubeconfig_sources', 'default_namespace', 'status', 'last_validated_at', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'error']
  - constraint: unique(context_name)
  - constraint: status in ('active','disabled','error')
- `api_keys.json` — API credentials for callers; used for authorization and quota enforcement on all tools. (11 rows; fields: ['id', 'key_hash', 'name', 'status', 'allowed_context_ids', 'allowed_namespaces', 'allow_mutations', 'rate_limit_rpm', 'burst_limit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: rate_limit_rpm between 1 and 60000
  - constraint: burst_limit between 1 and 10000
  - constraint: allow_mutations in (true,false)
- `k8s_operations.json` — Audited execution records for every tool invocation, including parameters, authorization context, and outcome. (35 rows; fields: ['id', 'api_key_id', 'context_id', 'tool_name', 'status', 'is_mutation', 'requested_namespace', 'resource_type', 'resource_name', 'group', 'version', 'parameters', 'request_size_bytes', 'response_size_bytes', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(api_key_id) references api_keys.id
  - constraint: fk(context_id) references k8s_contexts.id
  - constraint: request_size_bytes >= 0
  - constraint: response_size_bytes is null or response_size_bytes >= 0
- `k8s_operation_results.json` — Stores potentially large outputs for operations (structured JSON, text, YAML) with retention controls. (35 rows; fields: ['id', 'operation_id', 'content_type', 'payload_text', 'payload_json', 'truncated', 'retention_expires_at', 'created_at', 'updated_at'])
  - lifecycle `truncated`: ['true', 'false']
  - constraint: fk(operation_id) references k8s_operations.id on delete cascade
  - constraint: exactly_one_of(payload_text, payload_json)
  - constraint: content_type in ('application/json','text/plain','application/yaml')
- `rate_limit_counters.json` — Rolling counters used to enforce per-key and per-context request limits and burst controls. (30 rows; fields: ['id', 'api_key_id', 'context_id', 'window_start_at', 'window_seconds', 'count', 'created_at', 'updated_at'])
  - lifecycle `window_seconds`: ['1', '10', '60']
  - constraint: fk(api_key_id) references api_keys.id on delete cascade
  - constraint: fk(context_id) references k8s_contexts.id
  - constraint: unique(api_key_id, context_id, window_start_at, window_seconds)
  - constraint: window_seconds in (1,10,60)

## Business rules enforced by the tools

- For any tool taking 'context' as an argument, the server must resolve it to k8s_contexts.context_name and require the resolved k8s_contexts.status = 'active' (otherwise fail with error_code = 'CONTEXT_DISABLED' or 'CONTEXT_NOT_FOUND').
- k8s_get_contexts must return all k8s_contexts where status in ('active','error','disabled') and may include last_validated_at/last_error for operator visibility.
- If api_keys.allowed_context_ids is not null, every operation's context_id must be in that allowlist; otherwise the request is rejected with error_code='FORBIDDEN_CONTEXT'.
- If api_keys.allowed_namespaces is not null and the tool supplies namespace (or requested_namespace is derived), then requested_namespace must be in the allowlist; otherwise reject with error_code='FORBIDDEN_NAMESPACE'.
- Mutating tools (k8s_create_resource, k8s_apply_resource, k8s_patch_resource, k8s_label_resource, k8s_annotate_resource, k8s_expose_resource, k8s_scale_resource, k8s_autoscale_resource, k8s_update_resources, k8s_set_resources_for_container, k8s_rollout_undo/restart/pause/resume, k8s_cordon_node/uncordon_node/drain_node/taint_node/untaint_node, k8s_pod_exec) require api_keys.allow_mutations = true; otherwise reject with error_code='MUTATIONS_DISABLED'.
- Every tool invocation must create a k8s_operations row with parameters capturing all tool arguments; tool argument mapping must populate requested_namespace/resource_type/resource_name/group/version when applicable.
- k8s_get_resources must store kind into k8s_operations.resource_type and group/version into the corresponding fields when provided; namespace may be null to indicate cluster-scoped queries.
- k8s_get_resource must store kind->resource_type and name->resource_name and require namespace not null for namespaced kinds; if namespace is null and kind is known namespaced, reject with error_code='NAMESPACE_REQUIRED'.
- k8s_get_pod_logs must enforce a maximum limit on returned log bytes per request; if exceeded, set k8s_operation_results.truncated=true and cap payload size.
- k8s_get_events must enforce limit between 1 and 1000; values outside this range are rejected with error_code='INVALID_LIMIT'.
- k8s_scale_resource requires replicas between 0 and 10000 inclusive; otherwise reject with error_code='INVALID_REPLICAS'.
- k8s_autoscale_resource requires min_replicas between 1 and 10000, max_replicas between 1 and 10000, and max_replicas >= min_replicas; cpu_percent between 1 and 100 inclusive.
- k8s_expose_resource must validate port between 1 and 65535 and if target_port is provided it must also be between 1 and 65535; protocol when provided must be one of ('TCP','UDP','SCTP').
- k8s_taint_node.effect must be one of ('NoSchedule','PreferNoSchedule','NoExecute'); k8s_untaint_node.effect if provided must be one of the same values.
- k8s_pod_exec must enforce an execution timeout ceiling (e.g., <= 300 seconds) even if timeout is null; results are stored with retention_expires_at set (short retention for exec output).
- Operations must follow lifecycle transitions: status can only move queued->running->(succeeded|failed|cancelled) and timestamps started_at/finished_at must be set consistently with transitions.
- Rate limiting: before creating/running an operation, increment rate_limit_counters for api_key_id (and optionally context_id) in 60s and 1s windows; if projected count exceeds api_keys.rate_limit_rpm in 60s window or api_keys.burst_limit in 1s window, reject with error_code='RATE_LIMITED' and do not run the cluster call.
- Result retention: k8s_operation_results.retention_expires_at must be set for potentially sensitive outputs (pod logs, pod exec, describe) and a background job must delete expired results; deleting a k8s_operations row must cascade delete its result rows.