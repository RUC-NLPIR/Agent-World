# Fibery MCP Server — local MCP environment

This backend powers an MCP server that connects to a user's Fibery workspace, exposes workspace schema (databases/fields), and proxies low-level Fibery API commands plus entity create/update operations. It stores tenant/workspace connection info, cached schema snapshots for fast describe/list operations, and a full audit log of tool calls (including raw Fibery commands, created/updated entity ids, and errors) with basic rate limiting.

Repository: https://github.com/Fibery-inc/fibery-mcp-server
Homepage: https://smithery.ai/server/@Fibery-inc/fibery-mcp-server

## Datastore

- `workspaces.json` — A connected Fibery workspace/tenant. Holds auth/connection configuration and operational status for the MCP server integration. (12 rows; fields: ['id', 'fibery_host', 'workspace_name', 'auth_type', 'api_token_ciphertext', 'status', 'last_schema_sync_at', 'schema_etag', 'rate_limit_per_minute', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'error']
  - constraint: unique(fibery_host)
  - constraint: rate_limit_per_minute >= 1
  - constraint: rate_limit_per_minute <= 600
  - constraint: status in ('active','disabled','error')
- `schema_snapshots.json` — Cached Fibery schema snapshots per workspace. Supports list_databases and describe_database without hitting Fibery every time; also allows describing related databases via stored relations. (11 rows; fields: ['id', 'workspace_id', 'status', 'schema_version', 'captured_at', 'databases', 'database_name_index', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['current', 'superseded', 'failed']
  - constraint: unique(workspace_id, schema_version)
  - constraint: schema_version >= 1
  - constraint: status in ('current','superseded','failed')
  - constraint: at_most_one_current_snapshot_per_workspace(workspace_id)
- `fibery_commands.json` — Audit log of tool invocations that call Fibery (query_database, create_entity, update_entity). Stores raw request payloads, derived targets (database/entity ids), and response metadata for debugging and compliance. (49 rows; fields: ['id', 'workspace_id', 'tool_name', 'status', 'database_name', 'request_payload', 'response_payload', 'error_payload', 'http_status', 'duration_ms', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: tool_name in ('query_database','create_entity','update_entity')
  - constraint: http_status is null or (http_status >= 100 and http_status <= 599)
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: finished_at is null or started_at is not null
- `entities.json` — Locally tracked Fibery entities created/updated through this MCP server, enabling idempotency, quick lookups, and linking command history to concrete Fibery ids. (34 rows; fields: ['id', 'workspace_id', 'database_name', 'fibery_id', 'status', 'last_fields', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['known', 'deleted', 'unknown']
  - constraint: unique(workspace_id, fibery_id)
  - constraint: fibery_id is uuid_string
  - constraint: status in ('known','deleted','unknown')
- `tool_invocations.json` — All MCP tool invocations including read-only tools (current_date, list_databases, describe_database) and Fibery-mutating/query tools. Used for auditing, observability, and rate-limit accounting. (34 rows; fields: ['id', 'workspace_id', 'tool_name', 'status', 'input_params', 'output_summary', 'error_message', 'fibery_command_id', 'schema_snapshot_id', 'started_at', 'finished_at', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['started', 'succeeded', 'failed']
  - constraint: tool_name in ('current_date','list_databases','describe_database','query_database','create_entity','update_entity')
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: finished_at is null or finished_at >= started_at
  - constraint: if tool_name in ('query_database','create_entity','update_entity') then fibery_command_id is not null

## Business rules enforced by the tools

- current_date returns server time (no DB write required) but SHOULD create a tool_invocations row with tool_name='current_date' for observability; workspace_id may be null.
- list_databases must read from the latest schema_snapshots row where workspace_id matches and status='current'; if none exists or is stale, the implementation must fetch schema from Fibery, insert a new schema_snapshots row (status='current'), and mark prior 'current' as 'superseded'.
- describe_database must return fields for the selected database and any related databases using schema_snapshots.databases; if database name is not found in the current snapshot, return an error and record tool_invocations.status='failed'.
- query_database must persist a fibery_commands row with tool_name='query_database' capturing the raw request_payload and set status transitions queued->running->(succeeded|failed); tool_invocations must reference fibery_command_id.
- create_entity must require a database_name and an entity payload in request_payload; on success it must upsert entities(unique(workspace_id,fibery_id)) with status='known' and set entities.last_fields to the written fields (best-effort).
- update_entity must require 'fibery/id' inside the entity payload; it must validate fibery_id is a UUID string; on success it must upsert entities(unique(workspace_id,fibery_id)) and update last_fields/last_seen_at.
- Rate limiting: before executing any Fibery-calling tool (query_database/create_entity/update_entity and schema refresh), count tool_invocations for that workspace in the last 60 seconds and reject if >= workspaces.rate_limit_per_minute.
- FK integrity: deleting a workspace is blocked if dependent schema_snapshots, fibery_commands, entities, or tool_invocations exist (or must cascade via explicit admin-only operation).
- At most one schema_snapshots row per workspace may have status='current' at any time; promoting a new snapshot to current must demote the previous one in the same transaction.