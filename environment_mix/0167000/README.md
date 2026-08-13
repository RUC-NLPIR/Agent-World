# Contentful Management Server — local MCP environment

This backend mirrors a subset of the Contentful Management domain so the server can list and manage Spaces, Environments, Content Types, Entries, Assets, and AI Actions, including publishing workflows. It stores versioned draft/published state, locale-aware field payloads, bulk operations (publish/unpublish/validate), and AI Action invocations/results for later retrieval.

Repository: https://github.com/ivo-toby/contentful-mcp
Homepage: https://smithery.ai/server/@ivotoby/contentful-management-mcp-server

## Datastore

- `spaces.json` — Top-level tenant container for content. Used by list_spaces/get_space and as the parent for environments and content models. (12 rows; fields: ['id', 'contentful_space_id', 'name', 'default_locale', 'available_locales', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(contentful_space_id)
  - constraint: name <> ''
  - constraint: json_array_length(available_locales) >= 1
  - constraint: default_locale IN available_locales
- `environments.json` — Environments within a space (e.g., 'master', 'staging'). Used by list_environments/create_environment/delete_environment and as a scope for content types, entries, assets, and AI actions. (20 rows; fields: ['id', 'space_id', 'contentful_environment_id', 'name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ready', 'creating', 'deleting', 'deleted']
  - constraint: fk(space_id) references spaces(id) on delete restrict
  - constraint: unique(space_id, contentful_environment_id)
  - constraint: name <> ''
- `content_types.json` — Content model definitions (fields, validations, displayField). Supports list/get/create/update/delete/publish for content types and is referenced by entries. (40 rows; fields: ['id', 'environment_id', 'contentful_content_type_id', 'name', 'description', 'display_field', 'fields_schema', 'sys_version', 'published_version', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'published', 'archived', 'deleted']
  - constraint: fk(environment_id) references environments(id) on delete restrict
  - constraint: unique(environment_id, contentful_content_type_id)
  - constraint: sys_version >= 1
  - constraint: published_version is null or published_version <= sys_version
- `content_items.json` — Unified storage for Entries and Assets in an environment. Supports create/get/update/delete/publish/unpublish for entries and assets, list_assets, and search_entries. Stores locale-keyed fields for entries and metadata/file info for assets. (43 rows; fields: ['id', 'environment_id', 'type', 'content_type_id', 'contentful_item_id', 'fields', 'asset_meta', 'sys_version', 'published_version', 'published_at', 'first_published_at', 'status', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'published', 'changed', 'archived', 'deleted']
  - constraint: fk(environment_id) references environments(id) on delete restrict
  - constraint: fk(content_type_id) references content_types(id) on delete restrict
  - constraint: unique(environment_id, type, contentful_item_id)
  - constraint: sys_version >= 1
- `ai_actions.json` — AI Actions definable and publishable within an environment, plus invocation tracking. Supports list/get/create/update/delete/publish/unpublish and invoke/get invocation result. (34 rows; fields: ['id', 'environment_id', 'contentful_ai_action_id', 'name', 'description', 'definition', 'sys_version', 'published_version', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'published', 'disabled', 'deleted']
  - constraint: fk(environment_id) references environments(id) on delete restrict
  - constraint: unique(environment_id, contentful_ai_action_id)
  - constraint: sys_version >= 1
  - constraint: published_version is null or published_version <= sys_version
- `ai_action_invocations.json` — Execution records for invoking AI Actions with variables and retrieving results later. Supports invoke_ai_action and get_ai_action_invocation. (36 rows; fields: ['id', 'ai_action_id', 'environment_id', 'request_variables', 'status', 'result', 'error', 'started_at', 'finished_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled', 'expired']
  - constraint: fk(ai_action_id) references ai_actions(id) on delete cascade
  - constraint: fk(environment_id) references environments(id) on delete restrict
  - constraint: environment_id must equal (select environment_id from ai_actions where id = ai_action_id)
  - constraint: status in ('succeeded') implies result is not null and error is null and finished_at is not null

## Business rules enforced by the tools

- All operations that target entries/assets/content types/AI actions must be scoped to an environment; environment must belong to an active space and have status = 'ready'.
- create_entry must require a valid content_type_id (Contentful content type id) that exists in content_types for the same environment; server maps it to content_types.id.
- For entries, every provided field value must be an object keyed by locale; each locale key must be in spaces.available_locales for the parent space of the environment; reject writes that omit locale keys.
- update_entry merges into existing content_items.fields at field-id and locale level; it must increment sys_version and set status to 'changed' if the entry was previously 'published'.
- delete_entry/delete_asset are soft deletes: set status='deleted' and deleted_at=now(); records may be hard-deleted asynchronously but must not appear in reads or searches once deleted.
- publish_entry/publish_asset transitions: allowed only from status in ('draft','changed'); on publish set published_version=sys_version, published_at=now(), first_published_at if null, and status='published'.
- unpublish_entry/unpublish_asset transitions: allowed only from status='published'; on unpublish set status='draft' (or 'changed' if there are unpublished changes recorded) and published_at remains last published timestamp.
- Bulk publish/unpublish accepts either a single contentful_item_id or an array of up to 100 ids; the operation must be atomic per item and return per-item success/failure; server must enforce max batch size 100.
- list_assets returns only content_items where type='asset' and status!='deleted', ordered by updated_at desc; default page size is 3 and pagination is implemented via skip/limit with limit capped at 3 for this tool.
- search_entries searches only content_items where type='entry' and status!='deleted'; it may filter by content_type_id and full-text match over string fields across locales; results must be restricted to the requested environment.
- bulk_validate validates up to N entries (server-defined cap, e.g., 100) by checking required fields from content_types.fields_schema, locale presence, and basic type compatibility; it must not mutate content_items except optionally recording validation output in an ephemeral response.
- Content type publish is only allowed when status='draft' and fields_schema is valid; publishing sets published_version=sys_version and status='published'. Updating a published content type sets status='draft' and increments sys_version.
- create_environment sets status='creating' then 'ready' when provisioned; delete_environment sets status='deleting' then 'deleted' and must reject deletes if any non-deleted content_items exist in the environment unless a force flag exists (not exposed by these tools).
- AI actions can be invoked only when ai_actions.status='published' and not deleted/disabled; invoke_ai_action creates an ai_action_invocations row with status='queued' and later transitions to terminal state.
- get_ai_action_invocation must return the invocation by id and must not expose invocations across environments/spaces outside the caller's scope.