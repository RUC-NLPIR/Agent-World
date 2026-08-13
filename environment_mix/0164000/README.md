# Echo Server — local MCP environment

This backend stores operational state for an Echo MCP server: who is calling it (API keys/clients), what requests were made, and what responses were returned. The main workflows are: authenticate/attribute calls to a client, record each tool invocation (echo/ping/version), and serve version/config information consistently across instances.

Repository: https://github.com/simonfraserduncan/echo-mcp
Homepage: https://smithery.ai/server/@simonfraserduncan/echo-mcp

## Datastore

- `api_clients.json` — Registered calling clients (humans, services, or integrations) and their credentials/limits for invoking tools on the Echo server. (12 rows; fields: ['id', 'name', 'status', 'api_key_hash', 'api_key_prefix', 'rate_limit_per_minute', 'notes', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(name)
  - constraint: unique(api_key_hash)
  - constraint: unique(api_key_prefix)
  - constraint: rate_limit_per_minute >= 1 AND rate_limit_per_minute <= 60000
- `tool_invocations.json` — Immutable log of each tool call (echo/ping/version), including request/response payloads and timing for auditing and debugging. (19 rows; fields: ['id', 'client_id', 'tool_name', 'status', 'request_json', 'response_json', 'http_status_code', 'error_code', 'error_message', 'duration_ms', 'ip_address', 'user_agent', 'trace_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'processing', 'succeeded', 'failed']
  - constraint: tool_name IN ('echo','ping','version')
  - constraint: status IN ('received','processing','succeeded','failed')
  - constraint: duration_ms IS NULL OR (duration_ms >= 0 AND duration_ms <= 300000)
  - constraint: http_status_code IS NULL OR (http_status_code >= 100 AND http_status_code <= 599)
- `server_releases.json` — Known server versions and the currently active version returned by the version tool (supports rollbacks and multi-instance consistency). (12 rows; fields: ['id', 'version', 'git_sha', 'status', 'released_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'deprecated']
  - constraint: unique(version)
  - constraint: status IN ('active','inactive','deprecated')
  - constraint: released_at <= updated_at
  - constraint: at_most_one_active_release: UNIQUE(status) WHERE status = 'active'

## Business rules enforced by the tools

- Calling ping must create a tool_invocations row with tool_name='ping', request_json='{}', and response_json containing the literal string "pong" (schema-free), transitioning status received->processing->succeeded (or ->failed on error).
- Calling version must read the single server_releases row with status='active' and return its version string; if none exists, version must fail and record tool_invocations.status='failed' with http_status_code=500.
- Calling echo must record a tool_invocations row with tool_name='echo' and request_json equal to the received parameters object (empty for this tool surface); the response_json must equal the server’s echo output and be stored verbatim.
- If an authenticated API key is presented, tool_invocations.client_id must reference api_clients.id; if the client status is not 'active', the request must be rejected and logged with status='failed' and http_status_code=401 or 403.
- Rate limiting: for each api_clients row, the number of tool_invocations created in any rolling 60-second window must not exceed rate_limit_per_minute; excess requests must be rejected and logged as failed with http_status_code=429.
- tool_invocations rows are append-only for request_json and tool_name after creation; only status, response_json, error fields, duration_ms, http_status_code, and updated_at may change to complete the lifecycle.
- Deletion constraints: api_clients cannot be deleted if referenced by any tool_invocations; server_releases cannot be deleted if status='active'.