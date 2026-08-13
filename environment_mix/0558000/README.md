# WhatsApp Personal Account Connector — local MCP environment

This backend stores a user's WhatsApp personal-account session, synced contacts, chats and messages, and an audit trail of outbound send attempts. Main workflows are: establish/maintain a WhatsApp Web session, sync chats/messages into local storage for fast search/listing, and enqueue/record outgoing messages with delivery state.

Repository: https://github.com/aukik/whatsapp-mcp-ts
Homepage: https://smithery.ai/server/@aukik/whatsapp-mcp-ts

## Datastore

- `accounts.json` — Represents a connected WhatsApp personal account (one per phone number/session) and its lifecycle/session metadata used by all tools. (12 rows; fields: ['id', 'display_name', 'phone_e164', 'wa_user_jid', 'status', 'session_blob', 'last_seen_at', 'sync_cursor', 'created_at', 'updated_at'])
  - lifecycle `status`: ['provisioning', 'qr_required', 'connected', 'disconnected', 'banned', 'deleted']
  - constraint: unique(phone_e164) where phone_e164 is not null
  - constraint: unique(wa_user_jid) where wa_user_jid is not null
  - constraint: status != 'deleted' implies session_blob may be null only when status in ('provisioning','qr_required','disconnected')
- `contacts.json` — Address book entries visible to the connected WhatsApp account, used by search_contacts and for chat participant resolution. (31 rows; fields: ['id', 'account_id', 'contact_jid', 'phone_e164', 'display_name', 'push_name', 'is_business', 'avatar_url', 'last_interaction_at', 'created_at', 'updated_at'])
  - constraint: unique(account_id, contact_jid)
  - constraint: is_business in (true,false)
- `chats.json` — Chat threads (1:1 or group) available to an account, used by list_chats and get_chat. (33 rows; fields: ['id', 'account_id', 'chat_jid', 'type', 'title', 'contact_id', 'is_archived', 'is_muted', 'unread_count', 'last_message_id', 'last_message_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'hidden', 'deleted']
  - constraint: unique(account_id, chat_jid)
  - constraint: type='direct' implies contact_id is not null
  - constraint: unread_count >= 0
- `messages.json` — Messages within chats, used by list_messages, search_messages, get_message_context, and to support send_message state tracking. (33 rows; fields: ['id', 'account_id', 'chat_id', 'remote_message_id', 'from_jid', 'to_jid', 'direction', 'type', 'text', 'media', 'quoted_remote_message_id', 'timestamp', 'delivery_status', 'failure_reason', 'is_deleted_for_me', 'created_at', 'updated_at'])
  - lifecycle `delivery_status`: ['received', 'queued', 'sent', 'delivered', 'read', 'failed']
  - constraint: unique(account_id, chat_id, remote_message_id)
  - constraint: timestamp is not null
  - constraint: delivery_status='failed' implies failure_reason is not null
  - constraint: is_deleted_for_me in (true,false)
- `outbound_message_jobs.json` — Queue/audit table for send_message requests; decouples API calls from WhatsApp network delivery and provides retry/error tracking. (30 rows; fields: ['id', 'account_id', 'chat_id', 'payload', 'status', 'attempt_count', 'max_attempts', 'last_error', 'sent_message_id', 'requested_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'processing', 'succeeded', 'failed', 'cancelled']
  - constraint: attempt_count >= 0
  - constraint: max_attempts between 1 and 10
  - constraint: status='succeeded' implies sent_message_id is not null

## Business rules enforced by the tools

- All read tools (search_contacts, list_chats, get_chat, list_messages, search_messages, get_message_context) operate within exactly one connected account; the implementation must resolve the active account (e.g., single-account deployment) and scope every query by account_id.
- search_contacts returns contacts for the active account from contacts, optionally ranked by (display_name, push_name, phone_e164) matches; only rows with contacts.account_id = active account are eligible.
- list_chats returns chats for the active account where status != 'deleted', sorted by last_message_at desc then updated_at desc; unread_count must be >= 0.
- get_chat returns exactly one chat for the active account by chats.id or chats.chat_jid (implementation choice); it must not return chats.status='deleted'.
- list_messages returns messages for the active account scoped to a chat (by chat_id and account_id) and must exclude messages where is_deleted_for_me=true by default.
- search_messages searches messages for the active account using text (messages.text) and optionally media metadata; it must ignore is_deleted_for_me=true and should prefer recent timestamp ties.
- get_message_context must return a window of messages around a target message identified by (chat_id, remote_message_id) or messages.id; the window is produced by ordering messages.timestamp and selecting N before/after, and may additionally follow quoted_remote_message_id to include the quoted message if present.
- send_message creates an outbound_message_jobs row in status='queued' and also creates (or later upserts) a corresponding messages row with direction='outbound' and delivery_status='queued'; on provider acknowledgement it transitions messages.delivery_status from queued->sent->delivered->read or ->failed, respecting the declared transitions.
- Outbound send jobs are only accepted when accounts.status='connected'; otherwise the job must be rejected or immediately marked failed with last_error set.
- Foreign key integrity: chats.account_id must equal contacts.account_id when chats.contact_id is set, and messages.account_id must match chats.account_id for the referenced chat_id.
- Uniqueness/integrity: messages.remote_message_id must be unique per (account_id, chat_id) to prevent duplicates during sync; repeated sync writes must upsert by (account_id, chat_id, remote_message_id).
- Soft deletion: setting chats.status='deleted' or messages.is_deleted_for_me=true must not physically delete rows; read tools must exclude deleted data unless explicitly needed for internal recovery.