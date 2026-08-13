# Brevo MCP — local MCP environment

This backend stores Brevo (Sendinblue) workspace configuration and operational data to power contact management, messaging (email/SMS/WhatsApp), campaigns, webhooks, conversations, ecommerce sync, CRM entities, custom events, and inbound email processing. The main workflows are: managing contacts and lists, sending transactional messages with tracking, running scheduled campaigns, syncing ecommerce/CRM data, receiving inbound events (webhooks/inbound emails), and supporting enterprise multi-tenant user/access management.

Repository: https://github.com/samihalawa/brevo-mcp
Homepage: https://smithery.ai/server/@samihalawa/brevo-mcp

## Datastore

- `workspaces.json` — Tenant boundary representing a Brevo account/workspace. Stores API credentials metadata, account settings, sender/domain configuration, quotas, and lifecycle state for enterprise multi-tenant usage. (18 rows; fields: ['id', 'brevo_account_id', 'name', 'status', 'default_sender_email', 'default_sender_name', 'verified_domains', 'folders', 'quota_daily_emails', 'quota_daily_sms', 'quota_daily_whatsapp', 'quota_daily_events', 'usage_today', 'brevo_api_key_fingerprint', 'timezone', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'closed']
  - constraint: unique(name)
  - constraint: quota_daily_emails >= 0
  - constraint: quota_daily_sms >= 0
  - constraint: quota_daily_whatsapp >= 0
- `principals.json` — Enterprise users and service principals for multi-tenant access. Used to attribute actions (sends/imports/updates) and enforce role-based permissions. (18 rows; fields: ['id', 'workspace_id', 'type', 'email', 'display_name', 'role', 'status', 'last_login_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'invited', 'disabled']
  - constraint: unique(workspace_id, email)
  - constraint: email is required when type = 'user'
- `contacts.json` — Unified contact store for email/SMS/WhatsApp marketing, transactional messaging, lists/segments membership, and deduplication. Supports bulk import and create-contact-with-list flows. (19 rows; fields: ['id', 'workspace_id', 'email', 'phone_e164', 'whatsapp_e164', 'first_name', 'last_name', 'attributes', 'list_ids', 'consent', 'status', 'source', 'external_ids', 'created_by_principal_id', 'updated_by_principal_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'unsubscribed', 'bounced', 'blacklisted', 'deleted']
  - constraint: at least one of (email, phone_e164, whatsapp_e164) must be non-null
  - constraint: unique(workspace_id, email) where email is not null
  - constraint: unique(workspace_id, phone_e164) where phone_e164 is not null
  - constraint: unique(workspace_id, whatsapp_e164) where whatsapp_e164 is not null
- `contact_import_jobs.json` — Bulk contact import jobs created by the bulk_contact_import tool. Stores raw input, parsing/mapping results, dedupe decisions, and applied changes for audit and retries. (19 rows; fields: ['id', 'workspace_id', 'requested_by_principal_id', 'status', 'input_format', 'raw_input', 'detected_schema', 'attribute_mapping', 'target_list_ids', 'dedupe_strategy', 'summary', 'error', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'analyzing', 'importing', 'completed', 'failed', 'cancelled']
  - constraint: raw_input length <= 5_000_000
  - constraint: target_list_ids length <= 50
  - constraint: dedupe_strategy != 'create_new' implies at least one unique key is detected per row (email/phone/whatsapp)
- `messaging_objects.json` — Single collection for messaging/campaign artifacts and operational logs across email/SMS/WhatsApp: templates, transactional sends, campaigns, schedules, tracking events, inbound emails, webhooks, and conversations. Polymorphic records keyed by object_type with required fields varying by type. (21 rows; fields: ['id', 'workspace_id', 'object_type', 'status', 'name', 'channel', 'subject', 'from_email', 'from_name', 'to_contact_id', 'to_address', 'template_id', 'payload', 'scheduled_for', 'send_provider_message_id', 'tracking', 'event_type', 'event_at', 'webhook_url', 'webhook_secret', 'enabled_events', 'retry_policy', 'conversation_thread_id', 'inbound_message_id', 'attachments', 'crm_link', 'ecommerce_link', 'created_by_principal_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'active', 'scheduled', 'sending', 'sent', 'delivered', 'opened', 'clicked', 'bounced', 'failed', 'paused', 'disabled', 'received', 'processed', 'archived', 'deleted']
  - constraint: object_type in (...) required
  - constraint: channel is required when object_type in ('email_transactional_send','sms_transactional_send','whatsapp_send','campaign')
  - constraint: template_id must reference a row with object_type in ('email_template','whatsapp_template') when non-null
  - constraint: conversation_thread_id must reference a row with object_type = 'conversation_thread' when non-null
- `business_objects.json` — Unified ecommerce + CRM storage for companies, deals, tasks, notes, products, orders, coupons, and payments. Allows tools (ecommerce/crm) to create/update/query entities and link them to contacts and messaging. (19 rows; fields: ['id', 'workspace_id', 'object_type', 'status', 'name', 'description', 'amount', 'currency', 'properties', 'contact_id', 'external_id', 'parent_object_id', 'created_by_principal_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'open', 'won', 'lost', 'pending', 'paid', 'refunded', 'cancelled', 'archived', 'deleted']
  - constraint: unique(workspace_id, object_type, external_id) where external_id is not null
  - constraint: amount >= 0 when amount is not null
  - constraint: currency must be 3 uppercase letters when non-null
  - constraint: parent_object_id cannot create cycles

## Business rules enforced by the tools

- All tools operate within a workspace; every created row must include workspace_id and must reference an existing workspaces.id.
- Enterprise tool actions must verify principals.status='active' and role authorization: read_only cannot mutate; analyst cannot send messages; support cannot change quotas or API credentials.
- contacts tool: creating/updating contacts must enforce uniqueness of email/phone/whatsapp within a workspace and require at least one identifier field.
- contact_with_list tool: on success it must (a) create/update a contacts row and (b) add the list id(s) to contacts.list_ids atomically; if any list id is invalid, the operation must fail without partial updates.
- bulk_contact_import tool: creating an import job inserts contact_import_jobs with status='queued' then transitions through analyzing/importing; it must write summary counts and error details; it must not exceed raw_input size limit and must enforce dedupe_strategy rules.
- email tool: sending transactional email inserts messaging_objects object_type='email_transactional_send' with channel='email', status='sending' then transitions to sent/failed; it must increment workspaces.usage_today.emails_sent and enforce workspaces.quota_daily_emails.
- email_with_tracking tool: must create an email_transactional_send row and immediately return tracking fields derived from messaging_objects.tracking plus send_provider_message_id; status transition cannot skip 'sending' -> ('sent'|'failed').
- sms tool: transactional SMS sends must enforce sms_opt_in when present in contacts.consent unless an override flag exists in payload; must increment workspaces.usage_today.sms_sent and enforce quota_daily_sms.
- whatsapp tool: WhatsApp sends must require whatsapp_e164 (either via to_contact_id or to_address) and must increment workspaces.usage_today.whatsapp_sent and enforce quota_daily_whatsapp.
- campaigns tool: campaign objects (messaging_objects object_type='campaign') must start as draft, may move to scheduled with scheduled_for set, then to sending at/after scheduled_for; cancelling a scheduled campaign sets status to disabled or deleted depending on retention policy.
- webhooks tool: webhook_subscription rows must have webhook_url and enabled_events; disabling a webhook sets status='disabled' and prevents future deliveries; secrets must be stored encrypted.
- events tool: custom events insert messaging_objects object_type='custom_event' with event_type='custom' and event_at set; must increment workspaces.usage_today.events_ingested and enforce quota_daily_events.
- inbound tool: inbound_email rows must start status='received' and transition to processed/failed; attachments must be persisted with storage_key and size and total attachment size must respect limits.
- conversations tool: conversation_thread and conversation_message rows must enforce that conversation_message.conversation_thread_id references an existing thread; deleting a thread must archive or delete its messages according to retention policy.
- account tool: changes to workspace sender/domain/folders must only be allowed when workspaces.status='active'; quotas cannot be reduced below current usage_today counts.
- crm and ecommerce tools: upserts must enforce unique(workspace_id, object_type, external_id) when external_id is provided; payments must have parent_object_id referencing an ecom_order when object_type='ecom_payment'.