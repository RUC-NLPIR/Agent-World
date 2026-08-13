# WhatsApp MCP Server — local MCP environment

This backend models a WhatsApp client session that syncs chats, contacts, and messages into a local store and exposes read/search tools plus a send-message mutation. Core workflows are: (1) query contacts/chats/messages with paging/sorting, (2) fetch a chat with optional last message, (3) fetch message context windows around a message, and (4) record outbound sends with delivery lifecycle.

Repository: https://github.com/jlucaso1/whatsapp-mcp-ts
Homepage: https://smithery.ai/server/@jlucaso1/whatsapp-mcp-ts

## Datastore

- `wa_accounts.json` — Represents a connected WhatsApp identity/session the MCP server operates on. All contacts/chats/messages are scoped to an account to support multiple devices/sessions and ensure tool calls read/write within the correct account. (12 rows; fields: ['id', 'wa_jid', 'display_name', 'status', 'last_sync_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disconnected', 'revoked']
  - constraint: unique(wa_jid)
  - constraint: status in ('active','disconnected','revoked')
- `contacts.json` — Known contacts for an account, keyed by WhatsApp JID. Used by search_contacts and as chat participants. (30 rows; fields: ['id', 'account_id', 'jid', 'phone_e164', 'display_name', 'nickname', 'status', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'blocked', 'deleted']
  - constraint: unique(account_id, jid)
  - constraint: jid like '%@s.whatsapp.net' OR jid like '%@c.us' OR jid like '%@g.us'
  - constraint: status in ('active','blocked','deleted')
- `chats.json` — Chat threads (1:1 or group) for an account. Supports list_chats/get_chat and scoping list_messages/search_messages by chat_jid. (33 rows; fields: ['id', 'account_id', 'jid', 'chat_type', 'name', 'last_message_id', 'last_active_at', 'unread_count', 'is_muted', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(account_id, jid)
  - constraint: unread_count >= 0
  - constraint: status in ('active','archived','deleted')
  - constraint: chat_type in ('direct','group','broadcast','unknown')
- `chat_participants.json` — Join table between chats and contacts to represent membership (especially for groups). Enables resolving chat metadata and participant search in clients (even though tools here don't directly expose it). (30 rows; fields: ['id', 'account_id', 'chat_id', 'contact_id', 'role', 'status', 'joined_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'left', 'removed']
  - constraint: unique(chat_id, contact_id)
  - constraint: role in ('member','admin','owner')
  - constraint: status in ('active','left','removed')
  - constraint: FK chat_participants.account_id must equal chats.account_id for chat_id
- `messages.json` — Messages exchanged in chats, including inbound synced messages and outbound messages sent via send_message. Supports list_messages, search_messages, and get_message_context. (36 rows; fields: ['id', 'account_id', 'chat_id', 'chat_jid', 'wa_message_id', 'sender_jid', 'direction', 'message_type', 'text', 'sent_at', 'status', 'failure_reason', 'reply_to_message_id', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'queued', 'sent', 'delivered', 'read', 'failed']
  - constraint: unique(account_id, wa_message_id) where wa_message_id is not null
  - constraint: sent_at is not null
  - constraint: direction in ('in','out')
  - constraint: message_type in ('text','image','video','audio','document','sticker','contact','location','reaction','system','unknown')

## Business rules enforced by the tools

- All tool operations must be scoped to exactly one active wa_accounts row; reads and writes must only return rows where account_id matches the active account.
- search_contacts(query) must perform a case-insensitive contains match over contacts.display_name, contacts.nickname, contacts.jid, and contacts.phone_e164 (if present), returning only contacts.status='active'.
- list_chats(limit,page,sort_by,query,include_last_message) must filter to chats.status in ('active','archived') and apply optional query as case-insensitive contains match over chats.name or chats.jid; sort_by='last_active' orders by chats.last_active_at desc nulls last then chats.id; sort_by='name' orders by chats.name asc nulls last then chats.id.
- get_chat(chat_jid, include_last_message) must resolve chats by (account_id, jid); if include_last_message=true and chats.last_message_id is not null, it must return that message if it belongs to the same chat_id/account_id.
- list_messages(chat_jid,limit,page) must resolve the chat then return messages for that chat_id ordered by sent_at desc, id desc with offset=page*limit and limit=limit; limit must be > 0 and page must be >= 0.
- get_message_context(message_id,before,after) must locate the target messages row by messages.id, then return up to 'before' messages with same chat_id where (sent_at,id) < (target.sent_at,target.id) ordered by sent_at desc, id desc; and up to 'after' messages where (sent_at,id) > (target.sent_at,target.id) ordered by sent_at asc, id asc; before/after must be >= 0.
- search_messages(query,chat_jid?,limit,page) must do a case-insensitive match over messages.text for messages.message_type='text'; if chat_jid is provided it must restrict to that chat; results ordered by sent_at desc, id desc with offset=page*limit.
- send_message(recipient,message) must (a) validate message length >= 1, (b) upsert a chats row for (account_id, jid=recipient) if missing with chat_type inferred from jid suffix, status='active', and (c) insert a messages row with direction='out', message_type='text', text=message, status='queued' then transition to 'sent'/'failed' asynchronously; chats.last_message_id and chats.last_active_at must be updated to the new message on successful insert.
- Status transitions in messages.lifecycle must be enforced: e.g., a message cannot move from 'delivered' back to 'sent', and 'failed' is terminal.
- Pagination guards: list_chats.limit and list_messages.limit must be within 1..100; search_messages.limit within 1..50; requests outside ranges must be rejected.