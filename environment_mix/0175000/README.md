# Email sending — local MCP environment

This backend stores outbound email send requests and their delivery lifecycle, including recipients, message content, provider delivery attempts, and API access control. The main workflow is: an API client authenticates with an API key, submits an email to send, the system creates a message and recipient rows, then runs one or more provider attempts until the message is delivered, bounced, or marked failed.

Repository: https://github.com/resend/mcp-send-email
Homepage: https://smithery.ai/server/@resend/mcp-send-email

## Datastore

- `api_keys.json` — API keys used by clients to authenticate and authorize email sending, including per-key quotas and status. (17 rows; fields: ['id', 'key_hash', 'key_prefix', 'label', 'status', 'rate_limit_per_minute', 'daily_send_limit', 'daily_send_count', 'daily_send_count_date', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix, label) -- label may be NULL; enforce unique only when label is non-null (partial unique)
  - constraint: rate_limit_per_minute >= 1 and rate_limit_per_minute <= 6000
  - constraint: daily_send_limit >= 0
- `email_messages.json` — Top-level outbound email message requests created by API calls. Contains headers/content and overall delivery status. (18 rows; fields: ['id', 'api_key_id', 'status', 'from_email', 'from_name', 'subject', 'text_body', 'html_body', 'headers', 'reply_to', 'tags', 'provider_message_id', 'error_code', 'error_message', 'queued_at', 'sent_at', 'finalized_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'sending', 'delivered', 'bounced', 'failed', 'cancelled']
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: from_email is valid email address format
  - constraint: length(subject) <= 998 when not null
  - constraint: at least one of (text_body, html_body) is not null
- `email_recipients.json` — Recipients for an email message, separated by type (to/cc/bcc) and with per-recipient delivery outcomes when available. (18 rows; fields: ['id', 'message_id', 'kind', 'email', 'name', 'status', 'provider_recipient_id', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'delivered', 'bounced', 'failed']
  - constraint: fk(message_id) references email_messages(id) on delete cascade
  - constraint: email is valid email address format
  - constraint: unique(message_id, kind, email) -- prevent duplicate recipients within the same kind
- `email_provider_attempts.json` — Each attempt to send an email message through an upstream provider (e.g., Resend). Captures request/response, timing, and retry behavior. (18 rows; fields: ['id', 'message_id', 'attempt_no', 'provider', 'status', 'request_payload', 'response_payload', 'http_status', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: fk(message_id) references email_messages(id) on delete cascade
  - constraint: attempt_no >= 1 and attempt_no <= 10
  - constraint: unique(message_id, attempt_no)
  - constraint: http_status is null or (http_status >= 100 and http_status <= 599)
- `send_requests.json` — Immutable audit log of each call to the send-email tool, including authentication principal, derived payload (if any), and resulting message id(s). (18 rows; fields: ['id', 'api_key_id', 'tool_name', 'request_parameters', 'resolved_payload', 'result_message_id', 'status', 'error_message', 'ip_address', 'user_agent', 'created_at', 'updated_at'])
  - lifecycle `status`: ['accepted', 'rejected', 'errored']
  - constraint: fk(api_key_id) references api_keys(id) on delete restrict
  - constraint: fk(result_message_id) references email_messages(id) on delete set null
  - constraint: request_parameters must validate against tool JSON schema (currently: empty object only)
  - constraint: if status = 'accepted' then result_message_id is not null

## Business rules enforced by the tools

- Calling the send-email tool must create exactly one send_requests row capturing the raw request parameters (an empty JSON object per current tool schema).
- If authentication fails or the api_keys.status is 'revoked', the send-email tool must write send_requests.status='rejected' and must not create an email_messages row.
- If the send-email tool accepts a request, it must (a) create an email_messages row with status='queued' and queued_at=now, (b) create at least one email_recipients row, and (c) set send_requests.result_message_id to that email_messages.id.
- At message creation time, the system must enforce that at least one of email_messages.text_body or email_messages.html_body is provided, and that there is at least one recipient across (to, cc, bcc).
- For each accepted send-email request, api_keys daily_send_count must be incremented atomically and must never exceed api_keys.daily_send_limit (unless the limit is 0 meaning unlimited, in which case it must not block).
- Rate limiting must enforce api_keys.rate_limit_per_minute as a sliding window or token bucket; requests beyond the limit must be rejected and logged in send_requests with status='rejected'.
- A background dispatcher must create email_provider_attempts rows and progress attempt status queued->running->(succeeded|failed); it must update email_messages.status according to the declared lifecycle transitions only.
- email_messages.status must be terminal once in (delivered,bounced,failed,cancelled); no further provider attempts may be created after terminal status.
- If a provider attempt succeeds, email_messages.status must transition to 'delivered' unless a subsequent provider webhook updates it to 'bounced' (allowed only from 'delivered' if configured); otherwise treat bounces as terminal from 'sending'.
- FK integrity must be preserved: deleting an email_messages row must cascade delete its email_recipients and email_provider_attempts rows.