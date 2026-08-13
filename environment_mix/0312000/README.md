# WhatsApp MCP - QR only — local MCP environment

This backend stores a local, queryable mirror of a WhatsApp account’s chats, contacts, and messages, plus outbound send/download jobs and associated media files. Read tools (search/list/get/context) execute filters over the synced entities, while write tools (send_message/send_file/send_audio_message/download_media) create delivery/download jobs that transition through lifecycle statuses and attach resulting message/media records.

Repository: https://github.com/s3cr1z/whatsapp-mcp
Homepage: https://smithery.ai/server/@s3cr1z/whatsapp-mcp

## Datastore

- `wa_contacts.json` — Known WhatsApp contacts for the connected account. Used for contact search and for mapping phone numbers/JIDs to display names. (18 rows; fields: ['id', 'jid', 'phone_number_e164', 'display_name', 'profile_pic_url', 'is_business', 'status', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'blocked', 'deleted', 'unknown']
  - constraint: unique(jid)
  - constraint: unique(phone_number_e164) where phone_number_e164 is not null
  - constraint: phone_number_e164 matches ^[0-9]{7,15}$ when not null
- `wa_chats.json` — Chats (direct and group) mirrored locally with metadata for listing and lookup by JID. Supports chat search, sorting, and last message inclusion. (19 rows; fields: ['id', 'chat_jid', 'chat_type', 'title', 'direct_contact_id', 'last_message_id', 'last_active_at', 'is_muted', 'is_archived', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'left', 'deleted']
  - constraint: unique(chat_jid)
  - constraint: direct_contact_id is not null implies chat_type = 'direct'
  - constraint: direct_contact_id is null implies chat_type in ('group','broadcast','unknown') OR title is not null
  - constraint: last_active_at is null or last_active_at <= updated_at
- `wa_chat_participants.json` — Join table for chat membership. Used to implement get_contact_chats for group membership and to enrich chat metadata. (19 rows; fields: ['id', 'chat_id', 'contact_id', 'role', 'joined_at', 'left_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'left', 'removed']
  - constraint: unique(chat_id, contact_id)
  - constraint: left_at is null or left_at >= joined_at
  - constraint: chat_id references wa_chats.id on delete cascade
  - constraint: contact_id references wa_contacts.id on delete cascade
- `wa_messages.json` — Messages mirrored locally plus locally-created outbound messages. Supports listing/filtering by date, sender phone number, chat JID, free-text query, and retrieving context around a message. (21 rows; fields: ['id', 'external_message_id', 'chat_id', 'chat_jid', 'sender_contact_id', 'sender_phone_number_e164', 'direction', 'message_type', 'text', 'sent_at', 'received_at', 'status', 'has_media', 'reply_to_external_message_id', 'raw_payload', 'created_at', 'updated_at'])
  - lifecycle `status`: ['synced', 'pending_send', 'sent', 'delivered', 'read', 'failed', 'deleted']
  - constraint: unique(external_message_id, chat_jid)
  - constraint: sent_at is not null
  - constraint: limit queries: sent_at indexed with (chat_jid, sent_at desc)
  - constraint: sender_phone_number_e164 matches ^[0-9]{7,15}$ when not null
- `wa_media_items.json` — Media attachments for messages and locally managed download/send operations. Powers download_media and stores local file paths produced by downloads, plus source paths for outbound sends. (20 rows; fields: ['id', 'message_id', 'external_message_id', 'chat_jid', 'media_kind', 'mime_type', 'file_name', 'file_size_bytes', 'local_path', 'source_path', 'sha256', 'download_status', 'last_error', 'created_at', 'updated_at'])
  - lifecycle `download_status`: ['not_requested', 'queued', 'downloading', 'available', 'failed']
  - constraint: unique(message_id) where media_kind is not null
  - constraint: file_size_bytes is null or file_size_bytes >= 0
  - constraint: local_path is not null implies download_status = 'available'
  - constraint: source_path is not null implies media_kind in ('image','video','audio','document','unknown')

## Business rules enforced by the tools

- search_contacts(query) performs case-insensitive substring match over wa_contacts.display_name and exact/substring match over wa_contacts.phone_number_e164 and wa_contacts.jid; only returns contacts where status != 'deleted'.
- list_chats(query, limit, page, include_last_message, sort_by) reads from wa_chats filtered by (title ILIKE query OR chat_jid ILIKE query) when query is provided; sort_by must be one of ['last_active','title'] (API defaults to 'last_active'); pagination uses limit/page with limit between 1 and 100 and page >= 0.
- get_chat(chat_jid, include_last_message) must return a single wa_chats row by unique chat_jid; if include_last_message=true it must join wa_messages on wa_chats.last_message_id.
- get_direct_chat_by_contact(sender_phone_number) must resolve the phone number to a contact via wa_contacts.phone_number_e164, then return wa_chats where chat_type='direct' and direct_contact_id matches; if multiple exist, return the most recently active (max last_active_at).
- get_contact_chats(jid, limit, page) resolves wa_contacts by jid then returns chats where (wa_chats.direct_contact_id = contact.id) OR (exists wa_chat_participants row for (chat_id, contact_id) with status='active'); limit between 1 and 100 and page >= 0.
- get_last_interaction(jid) resolves wa_contacts by jid then returns the newest wa_messages row where sender_contact_id = contact.id OR (wa_messages.chat_id is a direct chat with wa_chats.direct_contact_id = contact.id), ordered by sent_at desc.
- list_messages(after, before, sender_phone_number, chat_jid, query, limit, page, include_context, context_before, context_after) filters wa_messages by sent_at > after and/or sent_at < before when provided; by wa_messages.sender_phone_number_e164 when sender_phone_number is provided; by wa_messages.chat_jid when chat_jid is provided; by substring match on wa_messages.text when query is provided; limit between 1 and 100, page >= 0.
- When include_context=true in list_messages, each matched message must include up to context_before messages immediately preceding and context_after immediately following within the same chat_id ordered by sent_at; context_before/context_after must be between 0 and 50.
- get_message_context(message_id, before, after) looks up wa_messages by external_message_id=message_id and returns surrounding messages within the same chat_id ordered by sent_at, with before/after between 0 and 200.
- send_message(recipient, message) resolves recipient either as chat_jid (contains '@') or as phone_number_e164 (digits only). If phone number, the system must map to or create wa_contacts and ensure a direct wa_chats row exists (creating if needed), then insert a wa_messages row with direction='outbound', message_type='text', status='pending_send'; status transitions must follow the wa_messages lifecycle.
- send_file(recipient, media_path) and send_audio_message(recipient, media_path) must create an outbound wa_messages row (message_type derived: 'audio' for send_audio_message, otherwise inferred) with has_media=true and status='pending_send', plus a wa_media_items row with source_path=media_path; media_path/source_path must be an absolute path and must exist on disk at send time (application-level check).
- download_media(message_id, chat_jid) must locate wa_messages by external_message_id=message_id AND wa_messages.chat_jid=chat_jid, then create or update wa_media_items for that message setting download_status to 'queued' (or re-queue from 'failed'); upon completion it must set local_path and download_status='available'.