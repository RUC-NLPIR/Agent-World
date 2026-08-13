# Gmail MCP — local MCP environment

This backend stores a local, queryable representation of a user’s Gmail mailbox and settings, synchronized from Gmail and mutated via tools that mirror Gmail API actions (drafts/messages/threads/labels and mailbox settings). Main workflows include creating/sending drafts or messages, searching/listing messages/threads/drafts by Gmail query and labels with pagination, applying label modifications in batch, and managing account-level configuration such as delegates, forwarding, send-as aliases, S/MIME, and push notification watches.

Repository: https://github.com/shinzo-labs/gmail-mcp
Homepage: https://smithery.ai/server/@shinzo-labs/gmail-mcp

## Datastore

- `gmail_accounts.json` — Represents a connected Gmail mailbox (one per Google account) and stores profile + mailbox-level settings used by get_profile and settings tools. (18 rows; fields: ['id', 'google_user_id', 'email_address', 'history_id', 'messages_total', 'threads_total', 'status', 'imap_enabled', 'imap_expunge_behavior', 'imap_max_folder_size', 'pop_access_window', 'pop_disposition', 'display_language', 'auto_forwarding_enabled', 'auto_forwarding_email_address', 'auto_forwarding_disposition', 'vacation_enable_auto_reply', 'vacation_response_subject', 'vacation_response_body_plain_text', 'vacation_restrict_to_contacts', 'vacation_restrict_to_domain', 'vacation_start_time_ms', 'vacation_end_time_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'disconnected']
  - constraint: unique(google_user_id)
  - constraint: unique(email_address)
  - constraint: messages_total >= 0 OR messages_total IS NULL
  - constraint: threads_total >= 0 OR threads_total IS NULL
- `gmail_labels.json` — User-defined and system labels in a mailbox. Used by list/get/create/update/patch/delete label tools and label filters on list_messages/list_threads. (18 rows; fields: ['id', 'gmail_account_id', 'gmail_label_id', 'name', 'label_type', 'message_list_visibility', 'label_list_visibility', 'color_text', 'color_background', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: fk(gmail_account_id) references gmail_accounts(id) on delete cascade
  - constraint: unique(gmail_account_id, gmail_label_id)
  - constraint: unique(gmail_account_id, name) WHERE status = 'active'
  - constraint: color_text IS NULL OR color_text ~ '^#[0-9A-Fa-f]{6}$'
- `gmail_threads.json` — Threads in the mailbox. Used by get_thread/list_threads/modify_thread/trash_thread/untrash_thread/delete_thread and as the parent for messages. (18 rows; fields: ['id', 'gmail_account_id', 'gmail_thread_id', 'snippet', 'status', 'last_message_internal_date_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'trashed', 'deleted']
  - constraint: fk(gmail_account_id) references gmail_accounts(id) on delete cascade
  - constraint: unique(gmail_account_id, gmail_thread_id)
- `gmail_messages.json` — Messages and drafts stored as message-like entities (RFC 2822 raw, headers, bodies). Serves get_message/list_messages/send_message, and draft tools by representing drafts as messages with is_draft=true and draft_id set. (20 rows; fields: ['id', 'gmail_account_id', 'gmail_message_id', 'gmail_draft_id', 'thread_id', 'gmail_thread_id', 'is_draft', 'from_address', 'to', 'cc', 'bcc', 'subject', 'snippet', 'body_plain', 'body_html', 'raw_rfc2822_base64url', 'internal_date_ms', 'size_estimate_bytes', 'has_attachment', 'label_ids', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'sent', 'received', 'trashed', 'deleted']
  - constraint: fk(gmail_account_id) references gmail_accounts(id) on delete cascade
  - constraint: fk(thread_id) references gmail_threads(id) on delete set null
  - constraint: unique(gmail_account_id, gmail_message_id) WHERE gmail_message_id IS NOT NULL
  - constraint: unique(gmail_account_id, gmail_draft_id) WHERE gmail_draft_id IS NOT NULL
- `gmail_settings_entities.json` — Mailbox configuration entities beyond labels: delegates, filters, forwarding addresses, send-as aliases, S/MIME configs, and mailbox watch registrations. Supports all corresponding get/list/create/update/patch/delete/verify/watch/stop tools. (18 rows; fields: ['id', 'gmail_account_id', 'entity_type', 'external_key', 'scope_key', 'payload', 'status', 'is_default', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'pending_verification', 'deleted', 'stopped']
  - constraint: fk(gmail_account_id) references gmail_accounts(id) on delete cascade
  - constraint: unique(gmail_account_id, entity_type, external_key, scope_key)
  - constraint: entity_type != 'smime_info' implies is_default IS NULL OR is_default = false
  - constraint: entity_type = 'smime_info' implies scope_key IS NOT NULL

## Business rules enforced by the tools

- All tools operate within exactly one gmail_account (resolved from auth context); every read/write must filter by gmail_account_id to prevent cross-mailbox access.
- create_draft: if raw is provided, store raw_rfc2822_base64url and ignore to/cc/bcc/subject/body/includeBodyHtml; otherwise construct raw from to/cc/bcc/subject/body, persist parsed fields, and set is_draft=true, status='draft'.
- send_message: if raw is provided, ignore to/cc/bcc/subject/body/includeBodyHtml; create a gmail_messages row with status='sent' after provider confirms send. If threadId provided, persist gmail_thread_id.
- send_draft: only allowed when gmail_messages.is_draft=true and status='draft' and gmail_draft_id is not null; on success transition status to 'sent' and set is_draft=false (draft id may be retained for audit).
- delete_draft: only allowed for is_draft=true and status='draft'; transition to status='deleted' and clear gmail_draft_id (or keep but mark deleted) to prevent reuse.
- get_draft/list_drafts must return only records where is_draft=true and status='draft'; includeBodyHtml controls whether body_html is returned (body_html may still be stored).
- list_messages/list_threads/list_drafts: maxResults must be between 1 and 500 when provided; if omitted, service applies a safe default (e.g. 50).
- pageToken is an opaque cursor produced by the service; it must encode gmail_account_id and query constraints (q, labelIds, includeSpamTrash) and be rejected if used with different constraints.
- list_messages and list_threads labelIds filter matches ALL provided label IDs (intersection semantics).
- includeSpamTrash=false must exclude items whose label_ids contain 'SPAM' or 'TRASH' system labels; includeSpamTrash=true allows them.
- modify_message/modify_thread and batch_modify_messages: addLabelIds/removeLabelIds must reference existing gmail_labels.gmail_label_id for that mailbox; applying both add and remove for the same label id in one request is invalid.
- trash_message/untrash_message and trash_thread/untrash_thread must enforce lifecycle transitions: active/sent/received -> trashed, and trashed -> previous non-deleted state; delete_message/delete_thread always transitions to deleted and is irreversible.
- get_attachment requires a messageId that exists for the mailbox and an attachment id that belongs to that message; attachment data is fetched from provider and may be cached in-memory, but if persisted it must be stored as part of gmail_messages (not modeled separately due to collection limit).
- create_label requires name; update_label requires id and replaces provided mutable fields; patch_label updates only provided fields. System labels (label_type='system') cannot be renamed or deleted.
- create_filter requires both criteria and action objects; store them in gmail_settings_entities.payload with entity_type='filter' and external_key set to provider filter id; list/get/delete operate by that id.
- Delegates are stored with entity_type='delegate' and external_key=delegateEmail; add_delegate creates with status='pending_verification' or 'active' depending on provider response; remove_delegate transitions to deleted.
- Forwarding addresses are stored with entity_type='forwarding_address' and external_key=forwardingEmail; delete_forwarding_address transitions to deleted; get/list filter status!='deleted'.
- Send-as aliases are stored with entity_type='send_as' and external_key=sendAsEmail; verify_send_as transitions status to pending_verification and records verification sent timestamp inside payload; patch/update mutate payload fields.
- S/MIME configs are stored with entity_type='smime_info', scope_key=sendAsEmail, external_key=immutable smime id; insert_smime_info stores encryptedKeyPassword and pkcs12 in payload (at rest encryption required); set_default_smime_info must set is_default=true on exactly one active config for that alias and set others to false.
- watch_mailbox upserts entity_type='mail_watch' with external_key='current' and payload.topicName/labelIds/labelFilterAction; stop_mail_watch transitions that record to status='stopped' and clears provider watch metadata in payload.
- All updates must bump updated_at; soft-deleted entities (status='deleted') must not be returned by list_* tools unless the Gmail API would return them (this service should default to excluding).