# Klaviyo Enhanced Analytics Server — local MCP environment

This backend stores Klaviyo-like marketing data for an account: customer profiles, audiences (lists/segments), behavioral events (metrics), messaging assets and delivery objects (campaigns/flows/templates), commerce catalogs, governance objects (tags, webhooks), and a few ancillary resources (coupons/forms/reviews/images). The main workflows are CRUD over these resources, adding profiles to lists, recording events against profiles/metrics, updating flow lifecycle state, tagging arbitrary resources, and managing outbound webhooks and profile deletion requests.

Repository: https://github.com/ivan-rivera-projects/Klaviyo-MCP-Server-Enhanced
Homepage: https://smithery.ai/server/@ivan-rivera-projects/Klaviyo-MCP-Server-Enhanced

## Datastore

- `accounts.json` — Tenant/account boundary for all Klaviyo resources. All objects belong to exactly one account and are isolated for queries and mutations. (12 rows; fields: ['id', 'public_name', 'default_currency', 'timezone', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'closed']
  - constraint: unique(public_name)
  - constraint: timezone must be a valid IANA timezone string
- `profiles.json` — Customer/person profiles. Supports CRUD, GDPR-style deletion requests, and audience membership (lists/segments). (18 rows; fields: ['id', 'account_id', 'email', 'phone', 'external_id', 'first_name', 'last_name', 'location', 'properties', 'consent', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suppressed', 'deletion_requested', 'deleted']
  - constraint: fk(account_id) references accounts(id) on delete restrict
  - constraint: unique(account_id, email) where email is not null
  - constraint: unique(account_id, phone) where phone is not null
  - constraint: unique(account_id, external_id) where external_id is not null
- `audiences.json` — Audience containers for profiles: lists (static membership) and segments (rule-based). Used by get_lists/get_list/create_list, get_segments/get_segment, and add_profiles_to_list. (19 rows; fields: ['id', 'account_id', 'type', 'name', 'description', 'segment_definition', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: fk(account_id) references accounts(id) on delete restrict
  - constraint: unique(account_id, type, name)
  - constraint: segment_definition is null iff type = 'list'
  - constraint: segment_definition is non-null iff type = 'segment'
- `events_metrics.json` — Metrics catalog and event stream. Supports get_events/create_event and get_metrics/get_metric as well as query_metric_aggregates and campaign performance rollups. (17 rows; fields: ['id', 'account_id', 'record_type', 'metric_id', 'metric_name', 'metric_unit', 'profile_id', 'event_time', 'event_properties', 'event_value', 'source', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'ingested', 'invalid']
  - constraint: fk(account_id) references accounts(id) on delete restrict
  - constraint: if record_type='metric' then metric_name is not null and metric_id is null and profile_id is null and event_time is null
  - constraint: if record_type='event' then metric_id is not null and profile_id is not null and event_time is not null and metric_name is null
  - constraint: unique(account_id, metric_name) where record_type='metric'
- `resources.json` — Unified table for the remaining first-class objects: campaigns/campaign messages/flows/templates/catalogs/catalog items/tags/webhooks/coupons/forms/product reviews/images, plus join-like rows for list membership and tag assignments. This supports the broad read surface and the few mutations (create_template, update_flow_status, create_tag, add_tag_to_resource, create/delete_webhook, create_coupon_code, add_profiles_to_list, campaign recipient estimation, campaign metrics/performance). (19 rows; fields: ['id', 'account_id', 'resource_type', 'external_key', 'name', 'status', 'parent_id', 'profile_id', 'audience_id', 'tag_id', 'target_resource_id', 'target_resource_type', 'body', 'analytics', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'active', 'paused', 'archived', 'deleted', 'enabled', 'disabled', 'pending', 'fulfilled', 'failed']
  - constraint: fk(account_id) references accounts(id) on delete restrict
  - constraint: if resource_type='campaign_message' then parent_id is not null and parent_id references a resource_type='campaign'
  - constraint: if resource_type='catalog_item' then parent_id is not null and parent_id references a resource_type='catalog'
  - constraint: if resource_type='list_membership' then profile_id is not null and audience_id is not null and audience_id references audiences(id) where type='list'

## Business rules enforced by the tools

- All reads and writes are scoped to a single accounts.id; cross-account foreign key references are rejected.
- get_profiles returns profiles where account_id matches and status != 'deleted' unless explicitly requested by an internal admin mode.
- get_profile resolves by primary key; it must belong to the caller's account_id.
- create_profile requires at least one identifier: email or phone or external_id; if email/phone provided, they must be unique within the account.
- update_profile cannot change a profile from status='deleted' to any other status; updates to deleted profiles are rejected.
- delete_profile performs a soft delete: sets profiles.status='deleted' and deleted_at=now; it must also invalidate future event ingestion for that profile (new events become status='invalid').
- request_profile_deletion creates a resources row with resource_type='profile_deletion_request', status='pending', profile_id set; fulfilling the request transitions status to 'fulfilled' and then marks the profile as deleted.
- get_lists/get_list only return audiences where type='list'; get_segments/get_segment only return audiences where type='segment'.
- create_list inserts an audiences row with type='list', status='active', and unique(account_id,type,name) enforced.
- add_profiles_to_list creates resources rows with resource_type='list_membership' for each (audience_id, profile_id); duplicates are ignored or rejected per unique constraint; only audiences.type='list' is allowed.
- get_events returns events_metrics rows where record_type='event' and account_id matches; get_metrics returns rows where record_type='metric'.
- create_event requires (metric_id, profile_id, event_time); metric_id must reference a metric record (record_type='metric') in the same account; profile_id must reference a non-deleted profile in the same account.
- query_metric_aggregates computes aggregates over events_metrics(event) grouped by time buckets and/or filters derived from event_properties; only events with status='ingested' are included.
- get_campaigns/get_campaign return resources where resource_type='campaign'; get_campaign_message(s) return resource_type='campaign_message' filtered by parent_id.
- get_campaign_recipient_estimation uses either cached resources.analytics.recipient_estimate or computes from audience memberships and segment definitions; results must not count deleted profiles.
- get_campaign_metrics and get_campaign_performance read from resources.analytics; if missing, compute from events (e.g., opens/clicks/purchases) and persist back to analytics with updated_at bumped.
- get_flows/get_flow return resources where resource_type='flow'. update_flow_status may only transition among (draft, active, paused, archived) using the declared lifecycle transitions; attempting invalid transitions is rejected.
- get_templates/get_template read resources where resource_type='template'. create_template inserts a template with status='draft' and required body fields (html/text).
- get_catalogs/get_catalog_items/get_catalog_item read resources where resource_type='catalog' and 'catalog_item'; catalog_item must have parent_id referencing a catalog.
- get_tags/create_tag read/insert resources where resource_type='tag'; tag names are unique per account.
- add_tag_to_resource inserts a resources row with resource_type='tag_assignment' tying tag_id to target_resource_id; the target must exist in the same account; duplicates are prevented by unique(account_id, tag_id, target_resource_id).
- get_webhooks/create_webhook/delete_webhook operate on resources where resource_type='webhook'; delete_webhook sets status='deleted' (soft delete) and prevents delivery processing.
- get_coupons/create_coupon_code operate on resources where resource_type='coupon'; coupon external_key (code) must be unique per account and immutable after creation.
- get_forms/get_form read resources where resource_type='form'.
- get_product_reviews/get_product_review read resources where resource_type='product_review'.
- get_images/get_image read resources where resource_type='image'.