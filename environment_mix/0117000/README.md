# Vercel API Integration — local MCP environment

This backend stores cached representations of Vercel deployments, their lifecycle events, and the files produced as part of a deployment. The main workflows are: ingest/sync deployments and events from Vercel, allow clients to query deployment metadata and events, and perform mutating actions like canceling or deleting a deployment while preserving an audit trail.

Repository: https://github.com/ssdavidai/vercel-api-mcp-fork
Homepage: https://smithery.ai/server/@ssdavidai/vercel-api-mcp-fork

## Datastore

- `vercel_integrations.json` — Represents an installation/configuration of the Vercel API integration, including credentials scope and sync state. Used to authorize and scope all deployment reads/writes. (12 rows; fields: ['id', 'vercel_team_id', 'vercel_user_id', 'auth_type', 'access_token_ciphertext', 'access_token_last4', 'token_expires_at', 'status', 'last_sync_at', 'last_sync_cursor', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'error', 'disabled']
  - constraint: check((vercel_team_id is not null) <> (vercel_user_id is not null))
  - constraint: unique(vercel_team_id) where vercel_team_id is not null
  - constraint: unique(vercel_user_id) where vercel_user_id is not null
  - constraint: status in ('active','revoked','error','disabled')
- `deployments.json` — Cached deployment records mirrored from Vercel. Supports listing, fetching details, canceling, and deleting deployments. (19 rows; fields: ['id', 'integration_id', 'vercel_project_id', 'project_name', 'name', 'url', 'target', 'source', 'git_repo', 'git_ref', 'commit_sha', 'status', 'vercel_state', 'created_by', 'created_at', 'updated_at', 'started_at', 'ready_at', 'deleted_at', 'canceled_at'])
  - lifecycle `status`: ['queued', 'building', 'ready', 'error', 'canceled', 'deleted']
  - constraint: fk(integration_id) references vercel_integrations(id) on delete restrict
  - constraint: unique(integration_id, id)
  - constraint: check(deleted_at is null or status = 'deleted')
  - constraint: check(canceled_at is null or status = 'canceled' or status = 'deleted')
- `deployment_events.json` — Time-ordered events for a deployment (build logs, state transitions, warnings/errors). Used by getDeploymentEvents. (18 rows; fields: ['id', 'deployment_id', 'integration_id', 'sequence', 'event_type', 'level', 'message', 'payload', 'occurred_at', 'created_at', 'updated_at'])
  - constraint: fk(deployment_id) references deployments(id) on delete cascade
  - constraint: fk(integration_id) references vercel_integrations(id) on delete restrict
  - constraint: unique(deployment_id, sequence)
  - constraint: check(sequence >= 1)
- `deployment_files.json` — Files included in or emitted by a deployment. Supports listing and fetching file contents. (18 rows; fields: ['id', 'deployment_id', 'integration_id', 'path', 'sha256', 'size_bytes', 'content_type', 'encoding', 'storage', 'content_text', 'content_blob_key', 'status', 'listed_at', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['listed', 'fetching', 'available', 'unavailable', 'deleted']
  - constraint: fk(deployment_id) references deployments(id) on delete cascade
  - constraint: fk(integration_id) references vercel_integrations(id) on delete restrict
  - constraint: unique(deployment_id, path)
  - constraint: check(size_bytes is null or size_bytes >= 0)
- `api_requests.json` — Audit log of tool calls and their effects, used for troubleshooting, rate limiting, and replay protection for mutating operations. (19 rows; fields: ['id', 'integration_id', 'tool_name', 'request_params', 'deployment_id', 'deployment_file_id', 'status', 'http_status', 'error_code', 'error_message', 'latency_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ok', 'error', 'rate_limited']
  - constraint: fk(integration_id) references vercel_integrations(id) on delete restrict
  - constraint: fk(deployment_id) references deployments(id) on delete set null
  - constraint: fk(deployment_file_id) references deployment_files(id) on delete set null
  - constraint: check(latency_ms is null or latency_ms >= 0)

## Business rules enforced by the tools

- All tools must be executed in the context of exactly one vercel_integrations row with status='active'; otherwise the call is rejected and logged in api_requests with status='error'.
- getDeployments returns deployments filtered by integration_id and status != 'deleted' unless explicitly requested internally; results are ordered by created_at desc.
- getDeployment returns exactly one deployments row by (integration_id, deployment_id); if not found, the service must attempt an upstream fetch and then upsert the deployments row.
- getDeploymentEvents returns deployment_events for the requested deployment ordered by sequence asc; if events are missing, the service may backfill from upstream and must maintain unique(deployment_id, sequence).
- cancelDeployment is only allowed when deployments.status in ('queued','building'); on success it sets deployments.status='canceled' and deployments.canceled_at=now(), and appends a deployment_events row of event_type='audit' and level='info'.
- deleteDeployment performs a soft delete locally by setting deployments.status='deleted' and deployments.deleted_at=now(); it must also attempt upstream deletion and log the outcome in api_requests.
- listDeploymentFiles returns deployment_files for the deployment ordered by path asc; if missing, the service should fetch the file listing from upstream, upsert rows, and set status='listed' with listed_at populated.
- getDeploymentFileContents may only return content for a deployment_file with status in ('available','unavailable'); if status is 'listed' or 'fetching', the service must fetch contents from upstream, store inline up to a configured maximum size, otherwise store in blob and set storage='blob'.
- For deployment_files, exactly one of (content_text, content_blob_key) must be set based on storage; invalid combinations are rejected by constraint.
- When deployments.status transitions to 'ready' the service should set ready_at if null; when transitioning to 'building' set started_at if null; these updates must not violate time ordering constraints.
- Every tool invocation must create an api_requests row; for successful mutating actions (cancelDeployment/deleteDeployment) api_requests.deployment_id must be set.
- Rate limiting/quota (if enabled) is enforced per integration_id and tool_name; when exceeded the service returns an error and logs api_requests.status='rate_limited'.