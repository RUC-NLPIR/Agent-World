# Directus MCP Server — local MCP environment

This backend models a Directus-backed MCP server that proxies CRUD operations over arbitrary Directus collections and exposes system/metadata endpoints. It stores workspaces (Directus instances), credentials, discovered collection schemas, and an audit log of all MCP tool calls and item mutations for traceability and quotas.

Repository: https://github.com/pixelsock/directus-mcp
Homepage: https://smithery.ai/server/@pixelsock/directus-mcp

## Datastore

- `workspaces.json` — Represents a configured Directus instance (base URL) and its operational settings for the MCP server. (18 rows; fields: ['id', 'name', 'directus_base_url', 'status', 'last_healthcheck_at', 'last_error', 'request_timeout_ms', 'max_page_size', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'error']
  - constraint: unique(directus_base_url)
  - constraint: request_timeout_ms >= 1000 AND request_timeout_ms <= 120000
  - constraint: max_page_size >= 1 AND max_page_size <= 5000
- `api_keys.json` — Credentials used by the MCP server to authenticate to Directus or to authorize clients of this MCP service (depending on deployment). Stored as hashed secrets with scopes. (18 rows; fields: ['id', 'workspace_id', 'label', 'key_hash', 'auth_type', 'directus_static_token', 'directus_user_email', 'directus_user_password_enc', 'scopes', 'status', 'last_used_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, label)
  - constraint: expires_at IS NULL OR expires_at > created_at
  - constraint: auth_type='static_token' -> directus_static_token IS NOT NULL
  - constraint: auth_type='email_password' -> directus_user_email IS NOT NULL AND directus_user_password_enc IS NOT NULL
- `collections_catalog.json` — Cached Directus collection schemas discovered via getCollections for each workspace, including collection names and field metadata needed for validation and tooling. (19 rows; fields: ['id', 'workspace_id', 'collection_name', 'schema_json', 'is_system', 'status', 'refreshed_at', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'error']
  - constraint: unique(workspace_id, collection_name)
  - constraint: collection_name length >= 1
- `items_index.json` — Optional lightweight index of Directus items that have been read or mutated through the MCP server, enabling consistent delete/update auditing without mirroring full Directus data. (17 rows; fields: ['id', 'workspace_id', 'collection_name', 'directus_item_id', 'last_seen_at', 'last_mutation_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['present', 'deleted', 'unknown']
  - constraint: unique(workspace_id, collection_name, directus_item_id)
- `tool_calls.json` — Immutable audit log of all MCP tool invocations (read/write) including request/response metadata used for debugging, analytics, and rate limiting. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'tool_name', 'collection_name', 'directus_item_id', 'request_payload_json', 'response_status_code', 'response_body_json', 'error_message', 'duration_ms', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'failed', 'rejected']
  - constraint: duration_ms >= 0 AND duration_ms <= 600000
  - constraint: tool_name IN ('getItems','getItem','createItem','updateItem','deleteItem','getSystemInfo','getCollections')
  - constraint: tool_name IN ('getItems','createItem','getCollections','getSystemInfo') -> directus_item_id IS NULL
  - constraint: tool_name IN ('getItems','getItem','createItem','updateItem','deleteItem') -> collection_name IS NOT NULL

## Business rules enforced by the tools

- Every tool invocation MUST create a tool_calls row with request_payload_json equal to the received parameters object (empty object when no parameters are provided).
- getCollections MUST upsert collections_catalog rows for the targeted workspace (unique by workspace_id+collection_name) and set status='fresh' with refreshed_at=now() on success, or status='error' with last_error populated on failure.
- getSystemInfo MUST update workspaces.last_healthcheck_at on success; on failure it MUST set workspaces.status='error' and store workspaces.last_error.
- For CRUD tools (getItems/getItem/createItem/updateItem/deleteItem), the implementation MUST record tool_calls.collection_name; for item-specific tools (getItem/updateItem/deleteItem) it MUST also record tool_calls.directus_item_id.
- createItem and updateItem MUST, on success, upsert an items_index row (unique by workspace_id+collection_name+directus_item_id), set status='present', and set last_mutation_at=now().
- deleteItem MUST, on success, set the corresponding items_index.status='deleted' (creating it first with status='deleted' if it does not exist) and set last_mutation_at=now().
- getItem/getItems MUST, when items are returned successfully, upsert items_index rows for each observed item id with status='present' and last_seen_at=now().
- Calls authenticated by an api_key MUST be rejected (tool_calls.status='rejected') if api_keys.status != 'active', api_keys.expires_at is in the past, or the requested tool_name is not contained in api_keys.scopes.
- FK integrity: api_keys.workspace_id, collections_catalog.workspace_id, items_index.workspace_id, and tool_calls.workspace_id MUST reference an existing workspaces.id; tool_calls.api_key_id when present MUST reference an existing api_keys.id.
- Uniqueness constraints MUST be enforced: workspaces.directus_base_url unique; collections_catalog unique(workspace_id, collection_name); items_index unique(workspace_id, collection_name, directus_item_id); api_keys unique(workspace_id, label).
- Status transitions MUST follow declared lifecycle transitions; updates attempting invalid transitions MUST be rejected.