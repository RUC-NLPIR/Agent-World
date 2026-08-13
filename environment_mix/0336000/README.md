# Mail MCP Tool — local MCP environment

This backend stores mail accounts connected to the MCP tool, their folders, messages, recipients, and attachments, plus outbound send jobs and status tracking. Core workflows include sending single/bulk emails (with HTML/simple variants), listing/searching mailboxes, fetching message details/attachments, moving/deleting messages, and updating read/unread state while optionally waiting for replies.

Repository: https://github.com/shuakami/mcp-mail
Homepage: https://smithery.ai/server/@shuakami/mcp-mail

## Datastore

- `mail_accounts.json` — Connected mailbox identities and provider configuration used by the tool to send and retrieve emails (e.g., IMAP/SMTP or API-based). (12 rows; fields: ['id', 'display_name', 'email_address', 'provider', 'auth_type', 'auth_secret_ref', 'imap_host', 'imap_port', 'smtp_host', 'smtp_port', 'default_from_name', 'status', 'last_sync_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'error']
  - constraint: unique(email_address, provider)
  - constraint: imap_port is null or (imap_port >= 1 and imap_port <= 65535)
  - constraint: smtp_port is null or (smtp_port >= 1 and smtp_port <= 65535)
  - constraint: if provider = 'imap_smtp' then imap_host, imap_port, smtp_host, smtp_port must be non-null
- `mail_folders.json` — Mailbox folders/labels used for listing and moving messages. (25 rows; fields: ['id', 'mail_account_id', 'provider_folder_id', 'name', 'folder_type', 'parent_folder_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'hidden', 'deleted']
  - constraint: unique(mail_account_id, provider_folder_id)
  - constraint: unique(mail_account_id, name)
  - constraint: parent_folder_id is null or parent_folder_id != id
- `emails.json` — Inbound and outbound email messages tracked by the tool, including state used for listing/searching, moving/deleting, and read/unread operations. (36 rows; fields: ['id', 'mail_account_id', 'provider_message_id', 'internet_message_id', 'thread_id', 'direction', 'folder_id', 'from_name', 'from_email', 'to_emails', 'cc_emails', 'bcc_emails', 'subject', 'snippet', 'body_text', 'body_html', 'has_attachments', 'is_read', 'received_at', 'sent_at', 'deleted_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'purged']
  - constraint: unique(mail_account_id, provider_message_id)
  - constraint: has_attachments = true implies at least one row exists in email_attachments for this email
  - constraint: deleted_at is null when status = 'active'
  - constraint: deleted_at is not null when status in ('deleted','purged')
- `email_attachments.json` — Attachments metadata and storage pointers for emails; used by getAttachment. (36 rows; fields: ['id', 'email_id', 'provider_attachment_id', 'filename', 'mime_type', 'size_bytes', 'content_sha256', 'storage_location', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['metadata_only', 'cached', 'deleted']
  - constraint: unique(email_id, provider_attachment_id)
  - constraint: size_bytes is null or size_bytes >= 0
- `contacts.json` — Known contacts derived from sent/received messages and/or provider address book; used by getContacts and to assist send operations. (30 rows; fields: ['id', 'mail_account_id', 'email_address', 'display_name', 'source', 'last_seen_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suppressed']
  - constraint: unique(mail_account_id, email_address)
- `mail_send_jobs.json` — Outbound send queue and audit trail for sendMail/sendSimpleMail/sendHtmlMail/sendBulkMail and reply-wait correlation. (21 rows; fields: ['id', 'mail_account_id', 'job_type', 'template', 'from_email', 'from_name', 'to', 'cc', 'bcc', 'subject', 'body_text', 'body_html', 'attachment_refs', 'bulk_payload', 'related_in_reply_to_email_id', 'provider_outbound_message_id', 'created_email_id', 'attempt_count', 'last_error', 'scheduled_for', 'sent_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'sending', 'sent', 'failed', 'cancelled']
  - constraint: attempt_count >= 0
  - constraint: job_type = 'sendSimpleMail' implies body_text is not null
  - constraint: job_type = 'sendHtmlMail' implies body_html is not null
  - constraint: job_type = 'sendBulkMail' implies bulk_payload is not null

## Business rules enforced by the tools

- All tools operate within a selected mail_account_id context; if the tool runtime does not pass it explicitly, it must resolve a default active mail_accounts row for the caller, otherwise return an error.
- sendMail/sendSimpleMail/sendHtmlMail must create a mail_send_jobs row in status='queued' and transition it through 'sending' to 'sent' or 'failed'; failures must record last_error and increment attempt_count.
- sendBulkMail must persist the entire bulk recipient list and per-recipient variables in mail_send_jobs.bulk_payload; the worker must enforce a maximum recipients-per-job limit (e.g., <= 1000) and maximum total payload size (e.g., <= 1MB).
- listFolders reads from mail_folders where status in ('active','hidden') for the active account; deleted folders must not be returned.
- listEmails reads from emails where mail_account_id matches and status='active', typically ordered by received_at/sent_at descending; it may filter by folder_id.
- searchEmails performs full-text search over emails.subject, emails.snippet, emails.body_text, emails.body_html and may additionally filter by folder_id, is_read, direction, and received_at/sent_at ranges; results must exclude status!='active'.
- getEmailDetail returns the emails row plus associated email_attachments metadata; if body fields are null, the service may fetch/parse from provider and then update emails.body_text/body_html/snippet/has_attachments.
- getAttachment must only return attachments whose email_id belongs to the same mail_account_id context and whose status != 'deleted'; if storage_location is null it may fetch from provider, cache it, and transition status to 'cached'.
- deleteEmail must soft-delete by setting emails.status='deleted' and emails.deleted_at=now; a background sync may later mark 'purged' when provider confirms permanent deletion.
- moveEmail must atomically update emails.folder_id to a destination mail_folders.id within the same mail_account_id; moving a deleted/purged email is forbidden.
- markAsRead/markAsUnread update emails.is_read for a single email id; markMultipleAsRead/markMultipleAsUnread update emails.is_read for a set of ids; updates must be limited to emails with status='active'.
- waitForReply must correlate replies by thread_id or internet_message_id/in-reply-to headers: given a mail_send_jobs row (or related_in_reply_to_email_id), it should return the first inbound emails row in the same thread received after the original sent_at; if not found within the tool timeout window it returns a not-found/timeout response.
- getContacts returns contacts for the active account where status='active'; contacts.last_seen_at should be updated when any emails row is ingested containing that address.
- FK integrity must be enforced: emails.folder_id must reference a mail_folders row with the same mail_account_id; email_attachments.email_id must reference an existing emails row.
- Quota/rate limits (implementation-level) should cap send volume per account (e.g., messages/day) and attachment sizes (e.g., <= 25MB each); violations must fail the send job with status='failed' and a descriptive last_error.