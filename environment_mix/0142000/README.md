# Gmail API Integration Server — local MCP environment

This backend stores per-user Gmail connection state (OAuth tokens), a locally cached index of Gmail entities (messages, drafts, threads, labels) for fast reads/search, and configuration objects that mirror Gmail settings (filters, delegates, forwarding addresses, send-as aliases, S/MIME configs, and push notification watches). Write tools mutate the cache and also enqueue/record intended remote Gmail operations; read tools serve from cache where possible while tracking sync/consistency and lifecycle state (e.g., draft sent, message trashed).

Repository: https://github.com/HitmanLy007/gmail-mcp
Homepage: https://smithery.ai/server/@HitmanLy007/gmail-mcp

## Datastore

- `gmail_accounts.json` — A connected Gmail mailbox (one Google account) with OAuth credentials, profile data, and high-level sync state. All other entities are scoped to a gmail_account. (12 rows; fields: ['id', 'google_user_id', 'primary_email', 'history_id', 'messages_total', 'threads_total', 'oauth_access_token', 'oauth_refresh_token', 'oauth_token_expiry', 'scopes', 'status', 'last_sync_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'token_expired', 'revoked', 'disabled']
  - constraint: unique(google_user_id)
  - constraint: unique(primary_email)
  - constraint: created_at is required
  - constraint: updated_at is required
- `mail_objects.json` — Unified cache of Gmail user mail entities: messages, drafts, threads, and attachments. Supports listing/search, label modification, trash/untrash, permanent delete, draft send, and attachment retrieval. A single table keeps collections within the 3-6 requirement while still modeling the real domain. (28 rows; fields: ['id', 'gmail_account_id', 'object_type', 'gmail_id', 'thread_gmail_id', 'draft_message_gmail_id', 'internal_date_ms', 'snippet', 'subject', 'from_addr', 'to_addrs', 'cc_addrs', 'bcc_addrs', 'body_text', 'body_html', 'raw_rfc2822_base64url', 'label_gmail_ids', 'size_estimate', 'attachment_of_message_gmail_id', 'filename', 'mime_type', 'attachment_data_base64url', 'page_token', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'trashed', 'deleted', 'sent', 'cancelled']
  - constraint: unique(gmail_account_id, object_type, gmail_id)
  - constraint: object_type in ('message','draft','thread','attachment')
  - constraint: if object_type='attachment' then attachment_of_message_gmail_id is not null
  - constraint: if object_type='thread' then thread_gmail_id = gmail_id
- `labels.json` — User-created and system labels. Used to filter list_messages/list_threads and to add/remove labels on messages/threads. (31 rows; fields: ['id', 'gmail_account_id', 'gmail_label_id', 'name', 'message_list_visibility', 'label_list_visibility', 'color_text', 'color_background', 'label_type', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(gmail_account_id, gmail_label_id)
  - constraint: unique(gmail_account_id, name) where status='active' and label_type='user'
  - constraint: color_text matches '^#[0-9A-Fa-f]{6}$' when not null
  - constraint: color_background matches '^#[0-9A-Fa-f]{6}$' when not null
- `gmail_settings.json` — Mailbox settings and configuration objects that map to Gmail 'users.settings.*' and related resources: auto-forwarding, IMAP, POP, language, vacation responder, delegates, filters, forwarding addresses, send-as aliases, S/MIME configs, and watch subscriptions. (33 rows; fields: ['id', 'gmail_account_id', 'setting_type', 'provider_key', 'payload', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'pending_verification', 'disabled', 'deleted']
  - constraint: unique(gmail_account_id, setting_type, provider_key)
  - constraint: if setting_type in ('auto_forwarding','imap','pop','language','vacation','watch') then provider_key='singleton'
  - constraint: if setting_type='auto_forwarding' then payload.enabled is boolean and payload.emailAddress is string and payload.disposition in ('leaveInInbox','archive','trash','markRead')
  - constraint: if setting_type='imap' then payload.enabled is boolean and (payload.expungeBehavior is null or in ('archive','trash','deleteForever')) and (payload.maxFolderSize is null or payload.maxFolderSize between 0 and 1000000)
- `remote_operations.json` — Durable log/outbox of operations executed against Gmail API for idempotency, auditing, retries, and status reporting. Each tool invocation that mutates Gmail writes one operation row. (38 rows; fields: ['id', 'gmail_account_id', 'tool_name', 'request', 'idempotency_key', 'related_object_type', 'related_gmail_id', 'response', 'error', 'attempt_count', 'status', 'scheduled_at', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: attempt_count >= 0
  - constraint: unique(gmail_account_id, idempotency_key) where idempotency_key is not null
  - constraint: created_at is required
  - constraint: updated_at is required

## Business rules enforced by the tools

- All tool calls execute in the context of exactly one gmail_account; if gmail_accounts.status in ('revoked','disabled') then all mutating tools MUST be rejected.
- For list_messages/list_drafts/list_threads, maxResults if provided MUST be between 1 and 500; otherwise the server default must be <= 100.
- For any tool that accepts includeBodyHtml, the service MUST omit body_html unless includeBodyHtml=true, even if cached, to avoid oversized responses.
- create_draft/send_message: if raw is provided, the server MUST ignore to/cc/bcc/subject/body/includeBodyHtml and persist raw_rfc2822_base64url; if raw is not provided, the server MUST construct and persist a raw RFC2822 message from the structured fields.
- send_draft: on success, the corresponding mail_objects row with object_type='draft' MUST transition status from 'active' to 'sent' and a new/updated message object may be upserted with object_type='message'.
- delete_draft: MUST mark the draft as deleted (status='deleted') and create a remote_operations row; repeated deletes are idempotent.
- trash_message/untrash_message and trash_thread/untrash_thread MUST only transition between 'active' and 'trashed'; if a message/thread is status='deleted' the operation MUST be rejected.
- delete_message/delete_thread and batch_delete_messages MUST set status='deleted' for each targeted object; objects already deleted remain deleted (idempotent).
- modify_message/modify_thread and batch_modify_messages MUST validate that every label id in addLabelIds/removeLabelIds exists in labels for the same gmail_account and has status='active', otherwise reject the request.
- list_messages/list_threads with labelIds MUST return only objects whose label_gmail_ids contain ALL specified labelIds (AND semantics).
- get_attachment MUST only return attachment_data_base64url for an attachment whose object_type='attachment' and whose attachment_of_message_gmail_id equals the provided messageId; otherwise 404.
- create_label MUST enforce unique(gmail_account_id, name) among active user labels; update_label/patch_label MUST also enforce this uniqueness when changing name.
- delete_label MUST mark labels.status='deleted' and remove the deleted label id from mail_objects.label_gmail_ids in the same account (or keep but exclude from future add operations).
- update_auto_forwarding requires enabled,emailAddress,disposition; if enabled=true then emailAddress MUST match an existing active forwarding_address payload.forwardingEmail or the operation MUST fail.
- create_send_as with isPrimary=true MUST demote any existing active send_as alias with payload.isPrimary=true to false (single-primary invariant).
- verify_send_as MUST transition the send_as settings object to status='pending_verification' until a subsequent sync marks it active.
- set_default_smime_info MUST set exactly one smime_info per sendAsEmail as default inside payload (e.g., payload.isDefault=true); setting a new default MUST unset previous defaults for same sendAsEmail.
- watch_mailbox MUST upsert a single watch settings row (setting_type='watch', provider_key='singleton') and store topicName,labelIds,labelFilterAction in payload; stop_mail_watch MUST set that row to status='disabled'.
- All mutating tools MUST write a remote_operations row with status queued/running/succeeded/failed and increment attempt_count on retries; operations with the same idempotency_key MUST not execute twice.