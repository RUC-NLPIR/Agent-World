# n8n Workflow Builder — local MCP environment

This backend stores programmatically generated n8n workflow definitions, including their nodes and node-to-node connections. The primary workflow is accepting a create_workflow request, validating node names/types and connection integrity, persisting a workflow snapshot, and tracking lifecycle state (draft/active/etc.) for later execution or export.

Repository: https://github.com/Jimmy974/n8n-workflow-builder
Homepage: https://smithery.ai/server/@Jimmy974/n8n-workflow-builder

## Datastore

- `workflows.json` — Top-level n8n workflow container created via the API. Stores metadata and lifecycle status for a workflow definition. (17 rows; fields: ['id', 'status', 'version', 'node_count', 'connection_count', 'definition_hash', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'active', 'archived', 'deleted']
  - constraint: version >= 1
  - constraint: node_count >= 0
  - constraint: connection_count >= 0
  - constraint: unique(definition_hash) where status != 'deleted'
- `workflow_nodes.json` — Nodes belonging to a workflow. Each node corresponds to an n8n node with a type, name, and parameter object. (18 rows; fields: ['id', 'workflow_id', 'node_type', 'node_name', 'parameters', 'created_at', 'updated_at'])
  - lifecycle `status`: ['configured', 'invalid']
  - constraint: foreign key (workflow_id) references workflows(id) on delete cascade
  - constraint: unique(workflow_id, node_name)
  - constraint: length(node_name) between 1 and 255
  - constraint: length(node_type) between 1 and 255
- `workflow_connections.json` — Directed edges between workflow nodes, including output and input indexes. Represents tool parameter connections[]. (18 rows; fields: ['id', 'workflow_id', 'source_node_id', 'target_node_id', 'source_node_name', 'target_node_name', 'source_output', 'target_input', 'created_at', 'updated_at'])
  - lifecycle `status`: ['valid', 'invalid']
  - constraint: foreign key (workflow_id) references workflows(id) on delete cascade
  - constraint: foreign key (source_node_id) references workflow_nodes(id) on delete cascade
  - constraint: foreign key (target_node_id) references workflow_nodes(id) on delete cascade
  - constraint: source_output is integer and source_output >= 0
- `workflow_create_requests.json` — Audit and idempotency tracking for create_workflow tool calls, including request payload and validation outcome. (20 rows; fields: ['id', 'idempotency_key', 'workflow_id', 'request_nodes', 'request_connections', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'validated', 'persisted', 'failed']
  - constraint: unique(idempotency_key) where idempotency_key is not null
  - constraint: request_nodes length >= 1
  - constraint: if request_connections is null then treat as empty list
- `api_keys.json` — API authentication and quota enforcement for clients calling create_workflow. (16 rows; fields: ['id', 'key_hash', 'status', 'label', 'daily_create_limit', 'daily_create_used', 'window_start_at', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: daily_create_limit between 0 and 1000000
  - constraint: daily_create_used >= 0
  - constraint: daily_create_used <= daily_create_limit

## Business rules enforced by the tools

- create_workflow must create exactly one workflows row and at least one workflow_nodes row.
- Each nodes[].name must be unique within the workflow; otherwise the request is rejected and workflow_create_requests.status becomes failed.
- Each connection references existing nodes by name; connections[].source and connections[].target must match a nodes[].name within the same request.
- connections[].sourceOutput and connections[].targetInput default to 0 when omitted; both must be integers >= 0.
- On persistence, connections are stored with both the provided names (source_node_name/target_node_name) and resolved foreign keys (source_node_id/target_node_id). If name resolution fails, the request fails and no partial workflow data is committed.
- A connection cannot be a self-loop (source_node_id != target_node_id).
- If an idempotency_key is provided and a prior workflow_create_requests row exists with the same key and status=persisted, the service must return the existing workflow_id and must not create a new workflow.
- API keys with status=revoked cannot call create_workflow.
- Each successful create_workflow increments api_keys.daily_create_used; if daily_create_used would exceed daily_create_limit, the request must be rejected before creating any workflow records.
- workflows.definition_hash is computed from a canonical JSON serialization of nodes and connections (including defaults). The backend must prevent creation of duplicate active/draft workflows with identical definition_hash (unless prior is deleted).