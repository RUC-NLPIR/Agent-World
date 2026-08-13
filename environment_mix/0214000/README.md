# Meta Ads Interface — local MCP environment

This backend supports a Meta Ads MCP interface that caches authenticated access, mirrors key Meta Ads entities (ad accounts, campaigns, ad sets, ads, creatives, images, pages), and stores analytics and Ads Library search results for repeatable retrieval. Core workflows include: authenticate and cache a token, list/fetch/update/create objects in an ad account, fetch insights over time ranges/breakdowns, and search the Ads Library archive with persisted queries and results.

Repository: https://github.com/brnardo/meta-ads-mcp
Homepage: https://smithery.ai/server/@brnardo/meta-ads-mcp

## Datastore

- `meta_auth_sessions.json` — Stores Meta (or Pipeboard) authentication material and token caching metadata used by tools when access_token is omitted. Also stores generated login link artifacts for audits and troubleshooting. (12 rows; fields: ['id', 'principal_type', 'principal_id', 'meta_user_id', 'access_token_ciphertext', 'token_source', 'scopes', 'token_expires_at', 'status', 'last_used_at', 'last_login_link_url', 'last_login_link_expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'revoked']
  - constraint: unique(principal_type, principal_id) where status='active'
  - constraint: token_expires_at is null OR token_expires_at > created_at
- `ad_accounts.json` — Mirrors Meta ad accounts accessible via a token/user. Used to serve get_ad_accounts and get_account_info and as the parent for campaigns/adsets/ads/assets. (12 rows; fields: ['id', 'external_meta_account_id', 'auth_session_id', 'name', 'account_status', 'currency', 'timezone_name', 'business_id', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'archived']
  - constraint: unique(external_meta_account_id)
  - constraint: external_meta_account_id like 'act_%'
- `ad_objects.json` — Stores hierarchical Meta Ads objects (campaigns, ad sets, ads) in one table with typed rows. Supports listing and detail reads plus create/update writes for campaigns, ad sets, and ads. (37 rows; fields: ['id', 'account_id', 'object_type', 'external_meta_id', 'parent_campaign_external_id', 'parent_adset_external_id', 'name', 'objective', 'buying_type', 'bid_strategy', 'bid_cap', 'bid_amount_minor', 'daily_budget_minor_str', 'lifetime_budget_minor_str', 'spend_cap_minor_str', 'campaign_budget_optimization', 'special_ad_categories', 'ab_test_control_setups', 'targeting', 'optimization_goal', 'billing_event', 'start_time', 'end_time', 'frequency_control_specs', 'creative_external_id', 'tracking_specs', 'configured_status', 'effective_status', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `configured_status`: ['ACTIVE', 'PAUSED', 'DELETED', 'ARCHIVED']
  - constraint: unique(object_type, external_meta_id)
  - constraint: object_type='campaign' implies parent_campaign_external_id is null and parent_adset_external_id is null
  - constraint: object_type='adset' implies parent_campaign_external_id is not null and parent_adset_external_id is null
  - constraint: object_type='ad' implies parent_campaign_external_id is not null and parent_adset_external_id is not null
- `creative_assets.json` — Stores pages, uploaded images, ad creatives, and image-download artifacts used by get_account_pages, upload_ad_image, create_ad_creative, get_ad_creatives, get_ad_image, save_ad_image_locally, debug_image_download, and save_ad_image_via_api. (33 rows; fields: ['id', 'account_id', 'asset_type', 'external_meta_id', 'name', 'page_id', 'instagram_actor_id', 'image_hash', 'image_source_path', 'snapshot_url', 'local_file_path', 'output_dir', 'mime_type', 'byte_size', 'link_url', 'message', 'headline', 'description', 'call_to_action_type', 'raw_meta_payload', 'status', 'failure_reason', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'processing', 'failed', 'deleted']
  - constraint: asset_type='page' implies page_id is not null
  - constraint: asset_type='image_upload' implies image_hash is not null
  - constraint: asset_type='ad_creative' implies (external_meta_id is not null OR name is not null)
  - constraint: byte_size is null OR byte_size >= 0
- `analytics_and_archive.json` — Stores on-demand insights responses and Ads Library archive search queries/results, plus image download debug runs. This supports get_insights, search_ads_archive, debug_image_download and enables caching/replay. (38 rows; fields: ['id', 'job_type', 'auth_session_id', 'account_id', 'object_id', 'time_range', 'breakdown', 'level', 'search_terms', 'ad_type', 'ad_reached_countries', 'fields', 'limit', 'url', 'result_payload', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: limit is null OR (limit >= 1 AND limit <= 500)
  - constraint: job_type='insights_query' implies (object_id is not null AND level is not null)
  - constraint: job_type='ads_archive_search' implies (search_terms is not null AND ad_type is not null)
  - constraint: job_type='image_download_debug' implies (url is not null OR object_id is not null)

## Business rules enforced by the tools

- If a tool call omits access_token, the service must locate an active meta_auth_sessions row for the caller principal and use its decrypted token; if none exists or it is expired/revoked, the call must fail with an authentication error.
- get_ad_accounts(user_id): if user_id='me', the resolved meta_user_id must match meta_auth_sessions.meta_user_id when present; otherwise store/use the explicit user_id for the request audit.
- All list tools (get_ad_accounts, get_campaigns, get_adsets, get_ads, search_ads_archive) must enforce limit bounds: minimum 1; maximum 500 (even if the tool default is smaller).
- create_campaign must create an ad_objects row with object_type='campaign', configured_status in {ACTIVE, PAUSED} (default PAUSED), and persist all provided optional fields (special_ad_categories, budgets, buying_type, bid_strategy, bid_cap, spend_cap, campaign_budget_optimization, ab_test_control_setups).
- update_campaign must only modify fields present in the request; unspecified fields must remain unchanged. configured_status transitions must respect the lifecycle transitions declared for ad_objects.
- create_adset must create an ad_objects row with object_type='adset' and parent_campaign_external_id set to the provided campaign_id; it must reject creation if the campaign_id does not exist in ad_objects as object_type='campaign' for the same account_id (or if account ownership cannot be verified).
- update_adset must persist frequency_control_specs as an array of objects when provided; bid_amount must be stored in bid_amount_minor as a non-negative integer when provided.
- create_ad must create an ad_objects row with object_type='ad', parent_adset_external_id set, and creative_external_id set to the provided creative_id; it must reject creation if the referenced adset does not exist for the same account_id.
- update_ad must coerce tracking_specs input: if provided as a JSON string, it must parse into an array of objects and store in ad_objects.tracking_specs; if parsing fails, the call must fail validation (not store invalid data).
- get_campaigns(status_filter): the service must filter against configured_status and/or effective_status; if the filter does not match known enums, it must return a validation error rather than a silent no-op.
- get_ad_creatives(ad_id) must resolve the ad_objects row for object_type='ad' and then read/create corresponding creative_assets rows of asset_type='ad_creative' keyed by creative_external_id; if the ad has no creative_external_id, return an empty creative list.
- upload_ad_image must create a creative_assets row with asset_type='image_upload', store image_source_path and returned image_hash, and set status='active' only after Meta confirms upload; otherwise status='failed' with failure_reason.
- create_ad_creative must create a creative_assets row with asset_type='ad_creative' storing (name, image_hash, page_id, link_url, message, headline, description, call_to_action_type, instagram_actor_id) and store Meta's creative id in external_meta_id when returned.
- get_ad_image/save_ad_image_locally/save_ad_image_via_api must create or update a creative_assets row with asset_type='ad_image_snapshot' keyed to the ad (stored in raw_meta_payload) and populate snapshot_url and/or local_file_path; failures must be recorded with status='failed' and a non-null failure_reason.
- debug_image_download must persist a analytics_and_archive row with job_type='image_download_debug' including either url or ad_id (stored as object_id), and store detailed diagnostics in result_payload regardless of success/failure.
- get_insights must persist a analytics_and_archive row with job_type='insights_query' capturing object_id, normalized time_range, breakdown, and level; repeated identical queries within a short TTL may be served from the latest succeeded result_payload.
- search_ads_archive must persist a analytics_and_archive row with job_type='ads_archive_search' capturing search_terms, ad_type, ad_reached_countries, fields, and limit; result_payload must store the returned ads and paging cursors if present.