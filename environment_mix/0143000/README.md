# AgentMail MCP Server — local MCP environment

This backend stores email inboxes provisioned for an AgentMail account, along with conversation threads, individual messages, and drafts. The main workflows are: create/provision an inbox, receive/sync inbound messages into threads, compose drafts or send/reply to messages (creating outbound messages), and list/get resources across a single inbox or all inboxes.

Repository: https://github.com/agentmail-to/agentmail-mcp
Homepage: https://smithery.ai/server/@agentmail-to/agentmail-mcp

## Datastore

- `inboxes.json` — Provisioned mailboxes owned by an AgentMail account. Used for listing, retrieving, and scoping threads/messages/drafts. (18 rows; fields: ['id', 'display_name', 'email_address', 'provider', 'status', 'sync_state', 'last_synced_at', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['provisioning', 'active', 'paused', 'disabled', 'error']
  - constraint: unique(email_address)
  - constraint: display_name length between 1 and 200
  - constraint: email_address must be valid RFC5322-like format
  - constraint: last_synced_at IS NULL OR last_synced_at >= created_at
- `threads.json` — Conversation threads within an inbox. A thread groups related inbound/outbound messages by provider thread id and normalized subject/participants. (18 rows; fields: ['id', 'inbox_id', 'provider_thread_id', 'subject', 'participants', 'message_count', 'last_message_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: fk(inbox_id) references inboxes(id) on delete cascade
  - constraint: unique(inbox_id, provider_thread_id) where provider_thread_id is not null
  - constraint: message_count >= 0
  - constraint: participants must be a non-empty array when message_count > 0
- `messages.json` — Individual email messages (inbound and outbound). Supports reading, updating (flags/labels), sending, and replying. (18 rows; fields: ['id', 'inbox_id', 'thread_id', 'provider_message_id', 'direction', 'from_email', 'to_emails', 'cc_emails', 'bcc_emails', 'reply_to_emails', 'subject', 'body_text', 'body_html', 'headers', 'labels', 'is_read', 'sent_at', 'status', 'in_reply_to_message_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'queued', 'sending', 'sent', 'failed', 'deleted']
  - constraint: fk(inbox_id) references inboxes(id) on delete cascade
  - constraint: fk(thread_id) references threads(id) on delete set null
  - constraint: unique(inbox_id, provider_message_id) where provider_message_id is not null
  - constraint: direction='inbound' implies status in ('received','deleted')
- `drafts.json` — Composed but not-yet-sent email drafts. Can be listed, retrieved, created, and sent (which creates an outbound message and marks draft as sent). (18 rows; fields: ['id', 'inbox_id', 'thread_id', 'reply_to_message_id', 'from_email', 'to_emails', 'cc_emails', 'bcc_emails', 'subject', 'body_text', 'body_html', 'headers', 'status', 'sent_message_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'sending', 'sent', 'discarded', 'error']
  - constraint: fk(inbox_id) references inboxes(id) on delete cascade
  - constraint: fk(thread_id) references threads(id) on delete set null
  - constraint: fk(reply_to_message_id) references messages(id) on delete set null
  - constraint: fk(sent_message_id) references messages(id) on delete set null

## Business rules enforced by the tools

- list_inboxes returns all inboxes with status in ('provisioning','active','paused','disabled','error') ordered by created_at desc.
- get_inbox retrieves a single inbox; if multiple inboxes exist and the tool provides no id, the implementation must default to a deterministic choice (e.g., most recently created active inbox) or raise a 400; backend enforces that the chosen inbox exists.
- create_inbox inserts a new inbox with status='provisioning', sync_state='not_configured', and a unique email_address; it may transition to 'active' asynchronously.
- list_threads returns threads filtered by a resolved inbox_id; list_all_threads returns threads across all inboxes.
- get_thread returns a thread by id and must enforce that the thread's inbox is accessible; it may optionally include derived aggregates from messages (message_count, last_message_at).
- list_messages returns messages filtered by a resolved inbox_id; list operations must not return messages with status='deleted' unless explicitly requested by internal code.
- get_message returns a single message by id; it must enforce inbox access and may join thread data via thread_id.
- send_message creates an outbound message row with direction='outbound', status='queued' (or 'sending'), and requires at least one recipient across to/cc/bcc and at least one body field (text or html).
- reply_to_message creates an outbound message with in_reply_to_message_id set, inherits thread_id from the original message (or creates/links a thread), and enforces that reply_to target belongs to the same inbox.
- update_message may only mutate mutable fields: is_read and labels (and optionally subject/body for drafts stored as messages is disallowed here); it must not change direction, from/to, or provider ids.
- list_drafts returns drafts for a resolved inbox_id with status in ('draft','sending','error') by default; list_all_drafts returns drafts across all inboxes.
- get_draft returns a draft by id and enforces inbox access.
- create_draft inserts a draft with status='draft' and validates recipient and body constraints similarly to send_message but allows empty body until sending depending on product policy; if empty body is allowed at create time, it must be blocked on transition to 'sending'.
- send_draft transitions a draft from 'draft' (or 'error') to 'sending', creates a corresponding outbound message (messages.direction='outbound'), sets drafts.sent_message_id, and finally transitions the draft to 'sent' if the message reaches 'sent'; failures set drafts.status='error' and messages.status='failed'.
- Foreign key integrity is enforced: threads.inbox_id must exist; messages.inbox_id must exist; messages.thread_id must belong to the same inbox_id when non-null; drafts.thread_id/reply_to_message_id must belong to the same inbox_id.
- Uniqueness constraints prevent provider duplication: (inbox_id, provider_thread_id) and (inbox_id, provider_message_id) must be unique when provided.
- Status transitions must follow the declared transition maps; direct updates that skip allowed transitions must be rejected.