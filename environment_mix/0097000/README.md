# Webflow MCP Server — local MCP environment

This backend stores Webflow workspaces/sites and their editable resources: pages (metadata + content), CMS collections, and CMS items with draft/live variants. The main workflows are: list/get sites and pages, update page settings or static content, manage CMS items in draft or live, publish selected items, and publish a site which promotes current draft content to live and creates a publish event record.

Repository: https://github.com/webflow/mcp-server
Homepage: https://smithery.ai/server/@webflow/mcp-server

## Datastore

- `sites.json` — Webflow sites accessible to the authenticated integration, including publishing state and domains. (17 rows; fields: ['id', 'workspace_id', 'name', 'short_name', 'webflow_subdomain', 'custom_domains', 'timezone', 'status', 'last_published_at', 'last_published_by', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'archived']
  - constraint: unique(workspace_id, name)
  - constraint: custom_domains is array of strings
  - constraint: status in ('active','disabled','archived')
- `pages.json` — Pages belonging to a site, including metadata/settings and stored static content snapshots for draft/live. (18 rows; fields: ['id', 'site_id', 'name', 'slug', 'path', 'page_type', 'collection_id', 'seo_title', 'seo_description', 'open_graph', 'canonical_url', 'is_password_protected', 'draft_content', 'live_content', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key(site_id) references sites(id) on delete cascade
  - constraint: foreign key(collection_id) references cms_collections(id) on delete set null
  - constraint: unique(site_id, slug)
  - constraint: path like '/%'
- `cms_collections.json` — CMS collections (content types) belonging to a site, including schema definition used to validate items. (19 rows; fields: ['id', 'site_id', 'name', 'slug', 'fields_schema', 'is_singleton', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: foreign key(site_id) references sites(id) on delete cascade
  - constraint: unique(site_id, slug)
  - constraint: fields_schema is array (min length 1)
  - constraint: is_singleton in (true,false)
- `cms_items.json` — CMS items within a collection. Stores both draft and live field data, and per-environment publish status to support create/update in draft vs live and publish actions. (18 rows; fields: ['id', 'collection_id', 'site_id', 'name', 'slug', 'draft_fields', 'live_fields', 'draft_status', 'live_status', 'is_archived', 'is_draft', 'last_published_at', 'created_at', 'updated_at'])
  - lifecycle `draft_status`: ['draft', 'pending_publish', 'archived']
  - constraint: foreign key(collection_id) references cms_collections(id) on delete cascade
  - constraint: foreign key(site_id) references sites(id) on delete cascade
  - constraint: unique(collection_id, slug)
  - constraint: draft_fields must conform to cms_collections.fields_schema (required fields present, types match)
- `publish_events.json` — Immutable log of publish operations for sites and CMS items, used to serve publish actions and audit/diagnostics. (18 rows; fields: ['id', 'site_id', 'event_type', 'collection_id', 'item_ids', 'domains', 'publish_mode', 'requested_by', 'status', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(site_id) references sites(id) on delete cascade
  - constraint: foreign key(collection_id) references cms_collections(id) on delete set null
  - constraint: event_type='items_publish' implies collection_id is not null
  - constraint: event_type='items_publish' implies item_ids is array with length >= 1

## Business rules enforced by the tools

- sites_list returns sites where status != 'archived' and workspace_id is authorized for the API caller.
- sites_get reads a single site by id; it must enforce tenant isolation by workspace_id.
- sites_publish creates a publish_events row with event_type='site_publish', status='queued', domains defaulting to sites.custom_domains plus webflow_subdomain when present; on completion it sets sites.last_published_at and sites.last_published_by and updates publish_events.status accordingly.
- pages_list returns pages for a given site_id (derived from caller context or selection) where status='active', ordered by path then name.
- pages_get_metadata reads pages.* metadata fields (name, slug, path, SEO/open_graph/canonical, protection) and must not expose draft/live content blobs unless requested via pages_get_content.
- pages_update_page_settings updates only metadata fields on pages (seo_title, seo_description, open_graph, canonical_url, slug, is_password_protected) and must preserve uniqueness of (site_id, slug); changing slug must also update path consistently.
- pages_get_content returns the draft_content by default; if the caller requests live content (implementation option), it returns live_content. Utility pages may have null content.
- pages_update_static_content updates pages.draft_content only; it must reject updates for page_type='collection_template'.
- collections_list returns cms_collections for a site where status='active'.
- collections_get returns a cms_collection including fields_schema; schema changes (not in tool surface) are not allowed through these tools.
- collections_items_list_items returns cms_items for a collection_id, filterable by draft/live status in implementation; archived items are excluded unless explicitly requested by an internal flag.
- collections_items_create_item creates a cms_items row with draft_fields populated, live_fields null, draft_status='draft', live_status='unpublished', is_draft=true; it must validate required fields per fields_schema and enforce unique(collection_id, slug).
- collections_items_update_items performs bulk updates within a single collection; each item update must validate schema, enforce slug uniqueness, and update updated_at; items with draft_status='archived' must be rejected.
- collections_items_create_item_live creates a cms_items row and immediately sets live_fields=draft_fields, live_status='published', is_draft=false, last_published_at=now and logs a publish_events row of type 'items_publish' including the new item id.
- collections_items_update_items_live performs bulk updates that affect both draft_fields and live_fields; it requires live_status='published' for each targeted item and logs a publish_events row with the affected item_ids.
- collections_items_publish_items creates a publish_events row event_type='items_publish' with provided item_ids; when succeeded, for each item it sets live_fields=draft_fields, live_status='published', is_draft=false, draft_status='draft', last_published_at=now.
- All mutating tools must update updated_at and must be atomic per request: either all intended items/pages are updated or none are (transactional behavior).
- Foreign key integrity must be enforced: pages.site_id must exist in sites; cms_collections.site_id must exist in sites; cms_items.collection_id must exist in cms_collections and cms_items.site_id must match cms_collections.site_id.