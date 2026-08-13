# Smartlead Campaign Management Server — local MCP environment

This backend stores outbound email campaigns (settings, schedules, sequences, and leads), plus Smart Delivery deliverability/spam tests (manual/automated) organized in folders. It also manages campaign webhooks and webhook publishing history, along with a lightweight clients model and SmartSenders domain/mailbox procurement workflow (vendors, domain search, mailbox generation, and order fulfillment).

Repository: https://github.com/jean-technologies/smartlead-mcp-server-local
Homepage: https://smithery.ai/server/@jean-technologies/smartlead-mcp-server-local

## Datastore

- `clients.json` — Tenant/customer records for the system, including optional white-label configuration. Campaigns, webhooks, tests, and procurement objects belong to a client. (31 rows; fields: ['client_id', 'name', 'status', 'whitelabel_enabled', 'whitelabel_config', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(lower(name)) where status != 'deleted'
  - constraint: whitelabel_enabled = false implies whitelabel_config is null OR whitelabel_config has only defaults
- `campaigns.json` — Email campaign core object including general settings, schedule, sequence steps, and campaign membership leads. Also stores analytics snapshots and supports export/download tracking. (43 rows; fields: ['campaign_id', 'client_id', 'name', 'status', 'settings', 'schedule', 'sequence_steps', 'analytics_daily_rollups', 'downloads', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'active', 'paused', 'completed', 'archived', 'deleted']
  - constraint: unique(client_id, lower(name)) where status != 'deleted'
  - constraint: json_schema_valid(settings) and json_schema_valid(schedule)
  - constraint: sequence_steps must be sorted by sequence_number and unique(sequence_number)
  - constraint: status = 'active' implies sequence_steps length >= 1
- `leads.json` — Lead/contact records plus membership in campaigns and per-campaign lead status. Supports single add, bulk import, status updates, and listing/filtering by campaign/status. (34 rows; fields: ['lead_id', 'client_id', 'email', 'first_name', 'last_name', 'company', 'title', 'phone', 'linkedin_url', 'website', 'custom_fields', 'status', 'campaign_memberships', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suppressed', 'deleted']
  - constraint: unique(client_id, lower(email)) where status != 'deleted'
  - constraint: campaign_memberships[*].campaign_id references campaigns.campaign_id and must have same client_id
  - constraint: campaign_memberships unique(campaign_id) per lead
  - constraint: campaign_lead_status enum within membership: ['queued','in_progress','replied','bounced','unsubscribed','completed','paused','removed']
- `smart_delivery_tests.json` — Deliverability/spam/placement tests (manual and automated), provider lists, mailbox usage, and test run history. Supports reports by provider/group/sender, and per-email details like content, headers, auth checks, blacklist, and IP analytics. (38 rows; fields: ['test_id', 'client_id', 'folder_id', 'test_type', 'name', 'status', 'schedule', 'providers', 'sender_accounts', 'receiver_mailboxes', 'runs', 'emails', 'aggregate_reports', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'scheduled', 'running', 'stopped', 'completed', 'deleted']
  - constraint: test_type = 'automated' implies schedule is not null
  - constraint: test_type = 'manual' implies schedule is null OR schedule has no recurrence
  - constraint: providers[*].provider_id must be valid for the provider catalog (maintained externally; cached in aggregate_reports.provider_catalog if needed)
  - constraint: sender_accounts length between 1 and 200
- `smart_delivery_folders.json` — Folders for organizing Smart Delivery tests; supports CRUD and listing all folders with contained tests. (32 rows; fields: ['folder_id', 'client_id', 'name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(client_id, lower(name)) where status = 'active'
  - constraint: cannot delete folder if it still has tests unless tests are moved or deleted (enforced at application layer)
- `integrations_and_procurement.json` — Combined table for campaign webhooks + publish attempts, plus SmartSenders domain/mailbox procurement (vendors, domain search cache, mailbox generation plans, and orders). Implemented as typed records with strict sub-schemas by record_type. (32 rows; fields: ['record_id', 'client_id', 'record_type', 'campaign_id', 'status', 'payload', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'queued', 'delivered', 'failed', 'retrying', 'cancelled', 'draft', 'placed', 'fulfilled', 'deleted']
  - constraint: record_type = 'campaign_webhook' implies campaign_id is not null and payload.url is a valid URL and payload.events length >= 1
  - constraint: unique(client_id, campaign_id, payload.url) where record_type='campaign_webhook' and status in ('active','inactive')
  - constraint: record_type = 'webhook_publish_event' implies campaign_id is not null and payload.attempt >= 1
  - constraint: retrigger_failed_events may only target record_type='webhook_publish_event' with status='failed'

## Business rules enforced by the tools

- All reads and writes are scoped to a client_id; cross-client access is rejected.
- smartlead_create_campaign creates a campaigns row with status='draft', default settings/schedule, and empty sequence_steps.
- smartlead_update_campaign_settings updates campaigns.settings and bumps updated_at; it must not change campaigns.status.
- smartlead_update_campaign_schedule updates campaigns.schedule and bumps updated_at; it must not change campaigns.status.
- smartlead_update_campaign_status is the only tool allowed to change campaigns.status; it must enforce the declared status transitions.
- smartlead_save_campaign_sequence replaces campaigns.sequence_steps atomically; sequence_number must start at 1 and be contiguous or explicitly allowed by settings, and must be unique within the campaign.
- smartlead_get_campaign_sequence reads campaigns.sequence_steps; smartlead_get_campaign_sequence_analytics reads campaigns.analytics_daily_rollups filtered by campaign_id and sequence_number.
- smartlead_list_campaigns filters by client_id and optionally by status/name; deleted campaigns are excluded by default.
- smartlead_delete_campaign sets campaigns.status='deleted' and deleted_at; hard delete is only allowed if there are no non-deleted webhook records referencing the campaign (or they are deleted in the same transaction).
- smartlead_add_lead_to_campaign upserts leads by (client_id,email) and adds/updates a campaign_memberships entry; membership must reference an existing non-deleted campaign owned by the same client.
- smartlead_bulk_import_leads performs the same upsert/join logic as add_lead_to_campaign for each row and must be idempotent for duplicate emails within the same import request.
- smartlead_update_lead modifies base lead fields and custom_fields; smartlead_update_lead_status changes only leads.status and enforces its lifecycle transitions.
- smartlead_list_leads supports filtering by campaign_id by scanning membership entries; filtering by lead status can apply to either leads.status and/or membership campaign_lead_status depending on endpoint semantics.
- smartlead_get_campaigns_by_lead returns all campaigns referenced in leads.campaign_memberships for that lead_id (excluding deleted campaigns by default).
- smartlead_export_campaign_leads generates CSV from leads joined through campaign_memberships for a campaign_id and records a downloads entry in campaigns.downloads (and updated_at).
- smartlead_download_campaign_data must write a downloads entry; smartlead_view_download_statistics reads aggregated counts from campaigns.downloads for the requested campaign and time window.
- Analytics endpoints (get_campaign_analytics_by_date, get_campaign_statistics, get_campaign_statistics_by_date, get_campaign_top_level_analytics, get_campaign_top_level_analytics_by_date, get_campaign_lead_statistics, get_campaign_mailbox_statistics) read from campaigns.analytics_daily_rollups; writes to rollups happen asynchronously and must be append-only per (campaign_id,date,sequence_number,mailbox_id) key.
- smartlead_get_region_wise_providers reads provider catalog entries stored as record_type='domain_vendor' payload.regions OR a separately maintained cached provider catalog inside smart_delivery_tests.aggregate_reports.provider_catalog; if missing, the service may refresh from upstream and store.
- smartlead_create_manual_placement_test inserts smart_delivery_tests with test_type='manual', status='running' or 'scheduled' depending on immediate execution; providers and sender_accounts must be non-empty.
- smartlead_create_automated_placement_test inserts smart_delivery_tests with test_type='automated', schedule present, and status='scheduled'.
- smartlead_stop_automated_test transitions an automated test from scheduled/running to stopped and sets schedule.next_run_at=null.
- smartlead_delete_smart_delivery_tests marks tests as deleted (status='deleted'); associated folder references remain but deleted tests are excluded from listings by default.
- smartlead_list_all_tests filters smart_delivery_tests by client_id, folder_id, type, and status; deleted excluded by default.
- Report endpoints (provider/group/sender/spam_filter/dkim/spf/rdns/blacklist/ip_analytics/ip_details/mailbox_summary/mailbox_count/schedule_history/email_content/email_headers/sender_accounts) must be served from smart_delivery_tests.emails, runs, and aggregate_reports and must validate that the requested email_id/run_id belongs to the test_id.
- smartlead_create_folder inserts smart_delivery_folders status='active'; delete folder sets status='deleted' and does not cascade delete tests.
- smartlead_upsert_campaign_webhook creates/updates a record_type='campaign_webhook' row keyed by (client_id,campaign_id,payload.url); enabling/disabling is stored in payload.is_enabled and/or status active/inactive.
- smartlead_fetch_webhooks_by_campaign lists campaign_webhook records by campaign_id with status in ('active','inactive') (excluding deleted).
- smartlead_delete_campaign_webhook sets the matching campaign_webhook record status='deleted'.
- smartlead_get_webhooks_publish_summary aggregates webhook_publish_event records by campaign_id, event_name, status, and time window.
- smartlead_retrigger_failed_events sets webhook_publish_event.status from failed->retrying and schedules payload.next_retry_at; it must increment payload.attempt and must not exceed a max attempts limit (e.g., 10).
- smartlead_get_vendors lists record_type='domain_vendor' with status='active'.
- smartlead_search_domain creates/updates a record_type='domain_search_cache' entry with query/pattern and results with an expiry; it must only return domains with price_usd < 15.
- smartlead_auto_generate_mailboxes creates a record_type='mailbox_generation_plan' entry; generated mailbox local parts must be unique per domain within the plan.
- smartlead_place_order_mailboxes creates a record_type='mailbox_order' entry with status='placed' and then, upon fulfillment, creates record_type='purchased_domain' entries with status='fulfilled' per domain and mailboxes.
- smartlead_get_domain_list lists record_type='purchased_domain' for a client_id where status != 'deleted'.