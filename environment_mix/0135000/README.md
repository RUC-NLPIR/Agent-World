# Telegram MCP Server — local MCP environment

This backend stores Telegram bot identity/configuration plus the operational message/update flow required to implement a Telegram MCP server. Core workflows are: reading bot metadata, ingesting updates from Telegram, sending/forwarding messages, and persisting audit/log records for traceability and idempotency.

Repository: https://github.com/NexusX-MCP/telegram-mcp-server
Homepage: https://smithery.ai/server/@NexusX-MCP/telegram-mcp-server

## Datastore

- `bots.json` — Registered Telegram bot connections (token/config) and cached bot identity used by get_bot_info and as the root FK for all other records. (12 rows; fields: ['id', 'bot_token_ciphertext', 'bot_token_fingerprint', 'telegram_bot_id', 'username', 'first_name', 'can_join_groups', 'can_read_all_group_messages', 'supports_inline_queries', 'webhook_enabled', 'last_getme_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'revoked']
  - constraint: unique(bot_token_fingerprint)
  - constraint: webhook_enabled IN (true,false)
  - constraint: status IN ('active','disabled','revoked')
- `chats.json` — Telegram chats (private/group/supergroup/channel) the bot has interacted with; used as destinations/sources for send_message and forward_message and for correlating updates. (18 rows; fields: ['id', 'bot_id', 'telegram_chat_id', 'type', 'title', 'username', 'status', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'blocked', 'unknown']
  - constraint: unique(bot_id, telegram_chat_id)
  - constraint: type IN ('private','group','supergroup','channel')
  - constraint: status IN ('active','blocked','unknown')
- `updates.json` — Incoming Telegram updates persisted for get_updates, deduplication, and replay. Stores raw payload plus parsed routing fields. (19 rows; fields: ['id', 'bot_id', 'telegram_update_id', 'update_type', 'chat_id', 'telegram_chat_id', 'telegram_message_id', 'raw_payload', 'received_at', 'status', 'processed_at', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'processed', 'failed', 'ignored']
  - constraint: unique(bot_id, telegram_update_id)
  - constraint: telegram_update_id >= 0
  - constraint: received_at IS NOT NULL
  - constraint: status IN ('queued','processed','failed','ignored')
- `messages.json` — Outbound and referenced inbound messages. Used to implement send_message (create outbound) and forward_message (create outbound linked to a source). (18 rows; fields: ['id', 'bot_id', 'direction', 'chat_id', 'telegram_chat_id', 'telegram_message_id', 'text', 'parse_mode', 'reply_to_telegram_message_id', 'source_message_id', 'source_telegram_chat_id', 'source_telegram_message_id', 'request_correlation_id', 'telegram_api_response', 'status', 'sent_at', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'queued', 'sent', 'delivered', 'failed', 'cancelled']
  - constraint: unique(bot_id, request_correlation_id) WHERE request_correlation_id IS NOT NULL
  - constraint: direction IN ('inbound','outbound')
  - constraint: parse_mode IN ('Markdown','MarkdownV2','HTML') OR parse_mode IS NULL
  - constraint: telegram_message_id >= 0 OR telegram_message_id IS NULL
- `tool_invocations.json` — Audit log for MCP tool calls (get_bot_info, send_message, get_updates, forward_message). Stores request/response payloads and outcome for debugging and rate/quota enforcement. (19 rows; fields: ['id', 'bot_id', 'tool_name', 'request_params', 'response_body', 'error_code', 'error_message', 'related_message_id', 'related_update_id', 'status', 'started_at', 'finished_at', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'failed']
  - constraint: tool_name IN ('get_bot_info','send_message','get_updates','forward_message')
  - constraint: status IN ('succeeded','failed')
  - constraint: duration_ms >= 0 OR duration_ms IS NULL
  - constraint: finished_at >= started_at OR finished_at IS NULL

## Business rules enforced by the tools

- Every tool invocation MUST be recorded in tool_invocations with tool_name matching the called tool and request_params equal to the received JSON object (empty object if none).
- get_bot_info MUST read bots where status='active'; if cached identity fields are null or last_getme_at is older than a configured TTL, it SHOULD refresh telegram_bot_id/username/etc and set last_getme_at.
- get_updates MUST persist each received Telegram update into updates and enforce idempotency by rejecting/inertly ignoring inserts that violate unique(bot_id, telegram_update_id).
- When ingesting an update containing a message/chat, the system MUST upsert chats by unique(bot_id, telegram_chat_id) and update last_seen_at; it SHOULD also create/refresh an inbound messages row linked to the update’s chat/message ids.
- send_message MUST create an outbound messages row with direction='outbound', status transitioning draft->queued->sent (or failed). It MUST populate chat_id/telegram_chat_id and MAY populate text/parse_mode/reply_to_telegram_message_id based on server-side defaults since the exposed tool surface has no parameters.
- forward_message MUST create an outbound messages row with source_telegram_chat_id and source_telegram_message_id set (and optionally source_message_id when the source exists locally). It MUST ensure the destination chat exists (or is created) and link it via chat_id.
- For outbound messages, telegram_message_id MUST be set only after Telegram acknowledges the send/forward; then sent_at MUST be set and status MUST become 'sent' (and optionally 'delivered' if the service tracks delivery).
- Bots with status='disabled' or 'revoked' MUST NOT send or forward messages; attempts must fail and be logged in tool_invocations with status='failed'.
- FK integrity MUST be enforced: chats.bot_id must reference an existing bots row; updates.bot_id must reference bots; messages.bot_id and messages.chat_id must reference existing rows; tool_invocations.bot_id must reference bots.
- Status transitions MUST follow each collection’s lifecycle.transition map; invalid transitions must be rejected.
- All created_at/updated_at fields MUST be set by the backend; updated_at MUST change on every mutation.
- request_correlation_id, when present, MUST provide idempotency for outbound message creation per unique(bot_id, request_correlation_id); retries with the same correlation id must return the original message result instead of duplicating sends.