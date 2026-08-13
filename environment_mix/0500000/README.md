# Kanka API Server — local MCP environment

This backend stores worldbuilding content for Kanka campaigns and exposes CRUD APIs for core entity types (characters, locations, notes, journals) plus entity posts. The main workflow is: an authenticated user selects a campaign, creates/updates entities within that campaign, optionally assigns tags and hierarchical parents, and manages per-entity posts with visibility and ordering.

Repository: https://github.com/ymgeva/kanka-mcp
Homepage: https://smithery.ai/server/@ymgeva/kanka-mcp

## Datastore

- `campaigns.json` — Campaigns (worlds) that contain all entities. Used by show_campaigns and as the top-level foreign key for all campaign-scoped content. (18 rows; fields: ['id', 'kanka_campaign_id', 'name', 'description', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(kanka_campaign_id)
  - constraint: name <> ''
- `entities.json` — Unified entity table for campaign content (characters, locations, notes, journals). Supports get/list/create/update/delete per type and provides entity_id for posts. (18 rows; fields: ['id', 'campaign_id', 'kanka_entity_id', 'entity_type', 'kanka_object_id', 'name', 'entry_html', 'type_label', 'title', 'age', 'sex', 'pronouns', 'race_id', 'is_destroyed', 'date', 'author_id', 'entity_image_uuid', 'parent_entity_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(campaign_id, entity_type, kanka_object_id)
  - constraint: unique(campaign_id, kanka_entity_id)
  - constraint: name <> ''
  - constraint: parent_entity_id IS NULL OR parent_entity_id <> id
- `posts.json` — Posts attached to an entity (entity notes/sidebars). Supports list/get/create/update/delete for posts by campaign_id and entity_id. (18 rows; fields: ['id', 'campaign_id', 'entity_id', 'kanka_post_id', 'name', 'entry_html', 'position', 'visibility_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(entity_id, kanka_post_id)
  - constraint: unique(campaign_id, entity_id, name)
  - constraint: name <> ''
  - constraint: position IS NULL OR position >= 0
- `tags.json` — Campaign-scoped tags which can be assigned to entities (characters/locations/notes/journals). Tools accept arrays of tag ids; this table enables FK integrity and reuse. (18 rows; fields: ['id', 'campaign_id', 'kanka_tag_id', 'name', 'color', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(campaign_id, kanka_tag_id)
  - constraint: unique(campaign_id, name)
  - constraint: name <> ''
- `entity_tags.json` — Join table mapping entities to tags. Powers tags arrays for create/update tools for locations/notes (and can support other entity types). (18 rows; fields: ['id', 'campaign_id', 'entity_id', 'tag_id', 'created_at', 'updated_at'])
  - constraint: unique(entity_id, tag_id)
  - constraint: campaign_id must equal entities.campaign_id for entity_id
  - constraint: campaign_id must equal tags.campaign_id for tag_id

## Business rules enforced by the tools

- show_campaigns returns campaigns where status != 'deleted'.
- All list_* tools filter by campaign and return only rows with status='active' for the requested entity_type.
- get_* tools must resolve by (campaign_id, entity_type, kanka_object_id) or by internal id; if status='deleted' return not-found.
- create_character/create_location/create_note/create_journal must create an entities row with entity_type set appropriately, require name, set status='active', and persist all provided optional fields to their mapped columns.
- update_character/update_location/update_note/update_journal must only update fields provided (patch semantics) and must not allow changing entity_type or campaign_id; moving parents updates parent_entity_id and must keep parent in same campaign.
- delete_character/delete_location/delete_note/delete_journal perform soft delete by setting entities.status='deleted' and updated_at=now; associated posts remain but must be inaccessible via list_posts for deleted entities.
- list_posts/get_post/create_post/update_post/delete_post require that the referenced entity exists in the same campaign and has status='active'.
- create_post requires entity_id (internal canonical) and name; stores entry as entry_html; position if provided must be >= 0.
- delete_post soft deletes by setting posts.status='deleted'; list_posts returns only posts.status='active' ordered by (position asc nulls last, created_at asc).
- When tools accept tags: each provided tag id must exist, belong to the same campaign, and have status='active'; entity_tags is replaced to match the provided list (idempotent set update).
- Uniqueness constraints must be enforced: (campaign_id, entity_type, kanka_object_id) unique; (campaign_id, kanka_entity_id) unique; (entity_id, kanka_post_id) unique.
- Parent relationships for hierarchical entities must not create cycles; at minimum prevent self-parenting and require parent_entity_id to reference an entity in the same campaign with a compatible entity_type (location parent must be location; note parent must be note; journal parent must be journal).