# Netlify MCP Server — local MCP environment

This backend models a Netlify MCP Server that brokers authenticated operations against the Netlify API while tracking local-to-remote site links, deployments/builds, environment variables, blobs, functions, forms, analytics pulls, and log streams. Core workflows are: select/switch an account, link or create sites, trigger/build/deploy and observe deploy status/logs, manage site configuration (env vars, branch deploys), interact with blobs and functions, and perform direct Netlify API calls with auditable request/response records.

Repository: https://github.com/DynamicEndpoints/Netlify-MCP-Server
Homepage: https://smithery.ai/server/@DynamicEndpoints/Netlify-MCP-Server

## Datastore

- `netlify_accounts.json` — Connected Netlify accounts/teams the MCP server can operate against, including credentials and active selection state. (12 rows; fields: ['id', 'netlify_account_id', 'display_name', 'auth_type', 'access_token_ciphertext', 'token_scopes', 'is_active', 'status', 'last_verified_at', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['connected', 'revoked', 'error']
  - constraint: unique(netlify_account_id)
  - constraint: at_most_one(is_active = true) across netlify_accounts
  - constraint: access_token_ciphertext must be non-empty when status in ('connected','error')
  - constraint: token_scopes length <= 128
- `sites.json` — Netlify sites accessible to the active account, including local project link metadata and configuration relevant to deploy/build operations. (28 rows; fields: ['id', 'account_id', 'netlify_site_id', 'name', 'custom_domain', 'default_domain', 'repo_url', 'repo_branch', 'build_command', 'publish_dir', 'local_repo_root', 'is_linked', 'branch_deploys', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleting', 'deleted', 'error']
  - constraint: unique(account_id, netlify_site_id)
  - constraint: unique(account_id, name)
  - constraint: is_linked = true implies local_repo_root is not null
  - constraint: local_repo_root is unique when not null (one directory can link to only one site)
- `deploys.json` — Deploy/build records for sites, including triggered builds, deployment status, and watchability. Powers list-deploys, get-deploy-info, trigger-build, deploy-site, build-site, cancel-deploy, restore-deploy, watch-deploy. (34 rows; fields: ['id', 'site_id', 'netlify_deploy_id', 'triggered_by', 'branch', 'commit_ref', 'deploy_url', 'admin_url', 'status', 'is_production', 'started_at', 'finished_at', 'duration_seconds', 'error_message', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'building', 'uploading', 'ready', 'failed', 'canceled', 'restoring']
  - constraint: unique(site_id, netlify_deploy_id)
  - constraint: duration_seconds is null or duration_seconds >= 0
  - constraint: finished_at is not null implies status in ('ready','failed','canceled')
  - constraint: started_at <= finished_at when both not null
- `site_kv.json` — Key/value storage scoped to a site for environment variables, blobs, and cached artifacts. Supports set/get/unset env vars, import/clone env vars, and blobs CRUD/list. (31 rows; fields: ['id', 'site_id', 'namespace', 'key', 'value_text', 'value_bytes', 'content_type', 'is_secret', 'etag', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(site_id, namespace, key) where status = 'active'
  - constraint: namespace = 'env' implies key matches ^[A-Z_][A-Z0-9_]*$
  - constraint: value_text is not null xor value_bytes is not null (exactly one set) when status='active'
  - constraint: namespace='env' implies value_bytes is null
- `observability_events.json` — Append-only operational and observability data: function logs, site logs, log stream sessions, function inventory snapshots, form submissions snapshots, recipe runs, dev server runs, analytics pulls, and direct Netlify API call audits. (36 rows; fields: ['id', 'account_id', 'site_id', 'deploy_id', 'event_type', 'status', 'request', 'response', 'http_method', 'http_path', 'http_status_code', 'error_message', 'started_at', 'ended_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'completed', 'failed', 'canceled']
  - constraint: http_status_code between 100 and 599 when not null
  - constraint: event_type='api_call_audit' implies http_method and http_path are not null
  - constraint: event_type in ('log_stream_session','dev_server_session','serve_session') implies started_at is not null
  - constraint: ended_at is not null implies status in ('completed','failed','canceled')

## Business rules enforced by the tools

- All tools execute under exactly one active netlify_accounts row (is_active=true); switch-account sets the previous active account to is_active=false and the chosen one to true atomically.
- list-sites/get-site-info/create-site/delete-site/link-site/unlink-site/set-env-vars/get-env-var/unset-env-var/import-env/clone-env-vars/list-deploys/get-deploy-info/cancel-deploy/restore-deploy/trigger-build/deploy-site/build-site/list-functions/get-form-submissions/enable-branch-deploy/disable-branch-deploy/get-analytics operate only on sites.status='active' unless the action is deletion or reading historical deploys.
- delete-site sets sites.status to 'deleting' then 'deleted' with deleted_at populated; once deleted, no new deploys may be created for that site and KV writes are rejected.
- link-site requires the target site to be active and enforces unique(local_repo_root); unlink-site clears local_repo_root and sets is_linked=false.
- set-env-vars/import-env/clone-env-vars upsert into site_kv where namespace='env'; unset-env-var marks the row status='deleted' and sets deleted_at. get-env-var returns redacted value when is_secret=true unless the tool explicitly requests reveal (not present in tool surface, so default redaction).
- Blob operations map to site_kv where namespace='blob': set-blob upserts (status='active'); get-blob reads active; delete-blob marks deleted; list-blobs returns keys for active blobs only.
- trigger-build/deploy-site/build-site create a deploys row with status='queued' and then update status through the allowed transitions as Netlify reports progress; cancel-deploy only allowed when status in ('queued','building','uploading') and transitions to 'canceled'.
- restore-deploy is allowed only when the referenced deploy exists for the same site; it creates or updates a deploy record with status='restoring' and then to 'ready' or 'failed'.
- watch-deploy and stream-logs create observability_events sessions with status='running' and must end with status in ('completed','failed','canceled') and ended_at set.
- call-netlify-api writes an observability_events row with event_type='api_call_audit' containing sanitized request/response and http_status_code; it must reject paths or bodies that would exfiltrate stored credentials (e.g., returning access_token_ciphertext).
- list-api-methods and get-status store snapshot responses in observability_events with event_type 'api_methods_snapshot' and 'get_status_snapshot' respectively; snapshots may be cached and reused for a short TTL (implementation choice) but must remain associated with the active account.
- list-functions/build-function/invoke-function-advanced store function inventory and invocation/build outputs in observability_events; invocations referencing a site must verify site_id belongs to the active account.
- manage-form and get-form-submissions store results/actions in observability_events; destructive form actions require an explicit action field in request payload (even if the tool schema is empty, the server must validate internally).
- get-analytics stores analytics snapshots in observability_events; requested date ranges (if provided internally) must be validated (start <= end) and bounded to prevent excessive API usage.
- Rate limiting/quota: per account, at most 60 tool executions per minute may be in status running/queued across observability_events and deploy creation; excess requests are rejected with a retry-after.