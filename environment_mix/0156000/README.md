# DeepView — local MCP environment

DeepView is an MCP-backed service that exposes a single operational tool used to deploy/claim a DeepView server instance for a client. The backend primarily stores server instances, claim/deployment events, and the client identities/credentials used to control access and enforce uniqueness and lifecycle transitions.

Repository: https://github.com/ai-1st/deepview-mcp
Homepage: https://smithery.ai/server/@ai-1st/deepview-mcp

## Datastore

- `clients.json` — Represents a distinct caller identity (e.g., MCP client installation, workspace, or API consumer) that can claim and manage DeepView server instances. (18 rows; fields: ['id', 'display_name', 'external_key', 'status', 'created_at', 'updated_at', 'last_seen_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(external_key)
  - constraint: display_name <> ''
- `server_instances.json` — A DeepView server instance that can be deployed and then claimed by a client. Stores the deployable endpoint and operational state. (17 rows; fields: ['id', 'client_id', 'status', 'region', 'endpoint_url', 'claim_token_hash', 'capacity_units', 'expires_at', 'last_healthcheck_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['provisioning', 'ready', 'claimed', 'failed', 'released', 'deleted']
  - constraint: capacity_units >= 1
  - constraint: capacity_units <= 1000
  - constraint: endpoint_url is null when status in ('provisioning')
  - constraint: client_id is null when status in ('provisioning','ready','released','failed')
- `deploy_claim_events.json` — Append-only event log capturing every invocation of the deepview tool and the resulting deploy/claim lifecycle actions. (20 rows; fields: ['id', 'client_id', 'server_instance_id', 'event_type', 'request_id', 'request_context', 'result', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `result`: ['ok', 'error']
  - constraint: unique(request_id)
  - constraint: request_context must be valid JSON object
  - constraint: error_code is null when result = 'ok'
  - constraint: error_message is null when result = 'ok'
- `api_keys.json` — Credentials used by clients to authenticate and claim/control DeepView server instances. Even if the MCP transport provides auth, production systems typically back it with an internal key record for revocation and quota enforcement. (18 rows; fields: ['id', 'client_id', 'key_prefix', 'key_hash', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(client_id, key_prefix)
  - constraint: key_prefix length >= 6

## Business rules enforced by the tools

- Invoking the deepview tool MUST create exactly one deploy_claim_events row with a new unique request_id per invocation.
- If the caller can be mapped to a clients.external_key, the deepview tool MUST upsert an active clients row and set deploy_claim_events.client_id accordingly; if the client is disabled, the tool MUST return an authorization error and record an error event.
- A server_instances row in status='claimed' MUST have non-null client_id and endpoint_url; a row in status in ('provisioning','ready','released','failed') MUST have client_id null.
- The tool MUST be idempotent by request_id: if the same request_id is seen again, it MUST return the previously computed outcome without creating additional server_instances rows.
- The system MUST enforce at most one concurrently claimed server_instances row per client_id (enforced by application logic: before claiming, check no other instance exists with status='claimed' for that client).
- When an instance is claimed, server_instances.status MUST transition to 'claimed' and server_instances.client_id MUST be set; the system MUST record claim_requested and either claim_succeeded or claim_failed events.
- If provisioning fails, server_instances.status MUST transition to 'failed' and the system MUST record deploy_failed with result='error' and a non-null error_code.
- Expired instances (expires_at < now) in status in ('ready','released','failed') MUST be transitioned to 'deleted' by a background job, and endpoint_url MUST NOT be reused until the old row is deleted (unique constraint on endpoint_url).
- capacity_units MUST be within [1, 1000] and is used to enforce per-client allocation limits; claims exceeding the configured per-client cap MUST be rejected with an error event.