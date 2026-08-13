# AppleScript MCP Server — local MCP environment

This backend powers an AppleScript-based MCP server that executes macOS automation tools (system controls, Finder, Calendar, Mail, Messages, Notes, iTerm, Pages, Shortcuts, Notifications) on behalf of authenticated clients. It stores API clients/keys, per-tool capability policy, and a durable execution log of every tool invocation including parameters, results, and errors for audit, debugging, and rate/quota enforcement.

Repository: https://github.com/femto/applescript-mcp
Homepage: https://smithery.ai/server/@femto/applescript-mcp

## Datastore

- `api_clients.json` — Represents an external client (agent/app) using the MCP server. Owns API keys and is the unit for quotas, allowlists, and audit reporting. (18 rows; fields: ['id', 'name', 'description', 'status', 'default_timezone', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: default_timezone is a valid IANA timezone string
  - constraint: status != 'deleted' required for authentication
- `api_keys.json` — API keys used to authenticate requests. Keys are stored as hashes; each belongs to one API client. (18 rows; fields: ['id', 'client_id', 'name', 'key_prefix', 'key_hash', 'status', 'last_used_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: foreign key (client_id) references api_clients(id) on delete restrict
  - constraint: unique(client_id, name)
  - constraint: unique(key_prefix)
  - constraint: expires_at is null or expires_at > created_at
- `tool_policies.json` — Per-client authorization and safety policy for each tool (allow/deny, parameter bounds, and high-risk actions like auto-send). Enforced before executing AppleScript. (18 rows; fields: ['id', 'client_id', 'tool_name', 'effect', 'parameter_constraints', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: foreign key (client_id) references api_clients(id) on delete cascade
  - constraint: unique(client_id, tool_name)
  - constraint: effect in ('allow','deny')
  - constraint: If tool_name='system_volume' and parameter_constraints.volume_max is set then 0 <= volume_max <= 100
- `tool_executions.json` — Durable log of every tool invocation (read or write) executed on the host. Stores request parameters, normalized fields for common filters, and execution outcome for audit and debugging. (20 rows; fields: ['id', 'client_id', 'api_key_id', 'tool_name', 'status', 'request_params', 'result_data', 'error_type', 'error_message', 'host_device_id', 'duration_ms', 'normalized', 'created_at', 'updated_at', 'started_at', 'finished_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key (client_id) references api_clients(id) on delete restrict
  - constraint: foreign key (api_key_id) references api_keys(id) on delete set null
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: started_at is null or started_at >= created_at
- `usage_quotas.json` — Rate/usage limits per client in a rolling or fixed window, used to protect the host from excessive automation and to bound high-risk tools (messages/mail/clipboard). (18 rows; fields: ['id', 'client_id', 'scope', 'tool_name', 'window_seconds', 'max_requests', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: foreign key (client_id) references api_clients(id) on delete cascade
  - constraint: window_seconds in [1, 86400]
  - constraint: max_requests in [1, 100000]
  - constraint: unique(client_id, scope, tool_name, window_seconds)

## Business rules enforced by the tools

- Every tool call must authenticate with an active api_key whose client is active; revoked/expired keys are rejected.
- Before executing any tool, the server must evaluate tool_policies for (client_id, tool_name); if no policy exists, default-deny (or server-configured default) must be applied consistently.
- If a tool is denied by policy, the server must create a tool_executions row with status='failed' and error_type='policy_denied' (no AppleScript execution).
- Request parameters must be validated against the tool JSON schema; invalid parameters must produce tool_executions.status='failed' with error_type='validation_error'.
- Quotas must be enforced per client: for each incoming tool call, count tool_executions created within now()-window_seconds for matching scope (all_tools plus tool-specific, both active) and reject if max_requests would be exceeded.
- tool_executions status transitions must follow the declared lifecycle; finished_at must be set when status is succeeded/failed/cancelled.
- High-risk actions must be explicitly allowed by policy constraints: messages_compose_message with auto=true, mail_create_email (if it triggers send in this implementation), clipboard_set_clipboard, and notifications_send_notification sound behavior must respect parameter_constraints when provided.
- For tools with documented defaults (e.g., clipboard_get_clipboard.type='text', mail_list_emails.count=10), the server must store the effective parameters in tool_executions.request_params after defaulting so audits are reproducible.
- host_device_id must be present for every execution and must match one of the server's configured host identities; mismatches are rejected and logged as failed executions.