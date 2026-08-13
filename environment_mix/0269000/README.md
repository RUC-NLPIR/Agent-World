# Figma MCP Server — local MCP environment

This backend stores the MCP server's linkage to Figma (OAuth/personal access tokens), a local catalog of teams/projects/files, and operational data for comments, reactions, webhooks, and analytics snapshots. Read tools primarily fetch from Figma and optionally hydrate/cache local entities; mutating tools (comments, reactions, webhooks) persist intent and outcomes with lifecycle/status to support retries, auditing, and idempotency.

Repository: https://github.com/thirdstrandstudio/mcp-figma
Homepage: https://smithery.ai/server/@thirdstrandstudio/mcp-figma

## Datastore

- `figma_accounts.json` — Represents an authenticated Figma user (the 'me' identity) and the credentials used by this MCP server to access Figma on their behalf. Also tracks token state, scopes, and last successful validation. (12 rows; fields: ['id', 'figma_user_id', 'handle', 'email', 'display_name', 'avatar_url', 'token_type', 'access_token_ciphertext', 'refresh_token_ciphertext', 'scopes', 'expires_at', 'status', 'last_validated_at', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'revoked', 'error']
  - constraint: unique(figma_user_id)
  - constraint: access_token_ciphertext is required
  - constraint: token_type = 'personal_access_token' implies refresh_token_ciphertext is null and expires_at is null
  - constraint: token_type = 'oauth_access_token' implies scopes is non-empty
- `figma_resources.json` — Locally tracked Figma entities used by the MCP server: teams, projects, files, components, component sets, and styles. This provides stable foreign keys for comments/webhooks/analytics and enables caching of metadata fetched via read tools. (33 rows; fields: ['id', 'account_id', 'resource_type', 'figma_key', 'parent_resource_id', 'name', 'description', 'url', 'file_key', 'team_id_key', 'library_published_at', 'raw_metadata', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted', 'unknown']
  - constraint: unique(account_id, resource_type, figma_key)
  - constraint: resource_type in ('component','component_set','style') implies file_key is not null
  - constraint: resource_type = 'file' implies parent_resource_id references a project or team (depending on org setup)
  - constraint: parent_resource_id cannot create cycles (enforced at application level)
- `figma_comments.json` — Comments in Figma files, including server-originated posts and deletions. Used to back get/post/delete comment tools and enables auditability and idempotent operations. (36 rows; fields: ['id', 'account_id', 'file_resource_id', 'figma_comment_id', 'parent_figma_comment_id', 'message', 'client_meta', 'order_id', 'created_by_figma_user_id', 'resolved', 'status', 'idempotency_key', 'last_error', 'figma_created_at', 'figma_updated_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['synced', 'pending_create', 'pending_delete', 'deleted', 'error']
  - constraint: file_resource_id must reference a figma_resources row with resource_type='file' (enforced at application level)
  - constraint: unique(account_id, file_resource_id, figma_comment_id) where figma_comment_id is not null
  - constraint: unique(account_id, idempotency_key) where idempotency_key is not null
  - constraint: message is required when status='pending_create'
- `figma_comment_reactions.json` — Reactions to comments (e.g., emoji). Supports fetching and creating/deleting reactions with idempotency and audit. (33 rows; fields: ['id', 'account_id', 'comment_id', 'figma_reaction_id', 'emoji', 'reacted_by_figma_user_id', 'status', 'idempotency_key', 'last_error', 'figma_created_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['synced', 'pending_create', 'pending_delete', 'deleted', 'error']
  - constraint: unique(account_id, comment_id, emoji, reacted_by_figma_user_id) where status in ('synced','pending_create') (best-effort; enforced at application level due to nullable reactor id)
  - constraint: unique(account_id, idempotency_key) where idempotency_key is not null
  - constraint: emoji length between 1 and 32
- `figma_webhooks.json` — Webhook registrations for teams. Supports create/get/update/delete and listing team webhooks, tracks delivery secret, endpoints, and verification state. (21 rows; fields: ['id', 'account_id', 'team_resource_id', 'figma_webhook_id', 'event_type', 'endpoint_url', 'passcode_ciphertext', 'active', 'status', 'idempotency_key', 'last_error', 'last_verified_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending_create', 'synced', 'pending_update', 'pending_delete', 'deleted', 'error']
  - constraint: team_resource_id must reference a figma_resources row with resource_type='team' (enforced at application level)
  - constraint: unique(account_id, team_resource_id, figma_webhook_id) where figma_webhook_id is not null
  - constraint: unique(account_id, team_resource_id, event_type, endpoint_url) where status in ('pending_create','synced','pending_update')
  - constraint: unique(account_id, idempotency_key) where idempotency_key is not null
- `figma_snapshots.json` — Durable snapshots of expensive/large read results and analytics: file versions, file nodes subsets, rendered images, image fills, team/library analytics usages. Used for caching, pagination, and reproducibility of responses. (39 rows; fields: ['id', 'account_id', 'resource_id', 'snapshot_type', 'request_fingerprint', 'params', 'payload', 'etag', 'fetched_at', 'expires_at', 'status', 'error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'purged', 'error']
  - constraint: unique(account_id, snapshot_type, request_fingerprint) where status in ('fresh','stale')
  - constraint: fetched_at <= now()
  - constraint: expires_at is null or expires_at >= fetched_at
  - constraint: payload size limits enforced at application level (e.g., <= 5MB JSON per row)

## Business rules enforced by the tools

- All tools must resolve an active figma_accounts row; if the account status is expired/revoked, tools must fail with an authentication error and set figma_accounts.status appropriately.
- figma_get_me reads from Figma and upserts into figma_accounts (by figma_user_id), updating profile fields and last_validated_at on success.
- For read tools that require a file/team/project/component/style key/id, the server must upsert the corresponding figma_resources row (unique by account_id, resource_type, figma_key) and attach parent_resource_id when determinable from the response.
- figma_get_file / figma_get_file_nodes / figma_get_images / figma_get_image_fills / figma_get_file_versions and the team/project/library analytics tools must write a figma_snapshots row keyed by (account_id, snapshot_type, request_fingerprint). If a fresh snapshot exists and is not expired, the tool may serve it instead of calling Figma.
- figma_get_comments must upsert figma_comments by (account_id, file_resource_id, figma_comment_id) and set status='synced' for records returned by Figma; local records in pending_delete may remain until confirmed deleted.
- figma_post_comment must create a figma_comments row with status='pending_create' and a non-null idempotency_key; on successful Figma creation it must set figma_comment_id, figma_created_at, and status='synced'.
- figma_delete_comment must transition the comment status from synced/error to pending_delete, call Figma, and on success set status='deleted'. Deleting an already-deleted comment must be idempotent and leave status='deleted'.
- figma_get_comment_reactions must upsert figma_comment_reactions rows for the comment; reactions removed in Figma should be marked deleted only if the API indicates removal (no blind deletes).
- figma_post_comment_reaction must create/update a figma_comment_reactions row with status='pending_create' and idempotency_key; on success set status='synced'.
- figma_delete_comment_reaction must transition from synced/error to pending_delete and on success set status='deleted'.
- figma_post_webhook must create a figma_webhooks row with status='pending_create' and idempotency_key; on success set figma_webhook_id and status='synced'.
- figma_update_webhook must only operate on status='synced' webhooks, transition to pending_update during the call, then return to synced on success (or error on failure).
- figma_delete_webhook must transition to pending_delete then deleted on success; repeat deletes must be idempotent.
- Team webhook listing (figma_get_team_webhooks) must upsert figma_webhooks by (account_id, team_resource_id, figma_webhook_id) and set status='synced' for any returned by Figma.
- Foreign key integrity must be enforced: comments and snapshots referencing a file/team must reference a figma_resources row of the correct resource_type (validated in application logic).
- Idempotency keys must be unique per account across comment, reaction, and webhook mutations; if a duplicate key is seen, the server must return the previously recorded outcome without duplicating the mutation.