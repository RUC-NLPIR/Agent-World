# Hugeicons MCP Server — local MCP environment

This backend stores the Hugeicons icon catalog (icons, tags, aliases) and platform-specific usage guides. Primary workflows are listing and searching icons by name/tags, and retrieving installation/usage instructions for a given frontend/mobile platform.

Repository: https://github.com/hugeicons/mcp-server
Homepage: https://smithery.ai/server/@hugeicons/mcp-server

## Datastore

- `icons.json` — Canonical icon records available in the Hugeicons set, including naming, metadata, and lifecycle state. (18 rows; fields: ['id', 'slug', 'display_name', 'category', 'style', 'keywords', 'status', 'version_introduced', 'version_deprecated', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'hidden']
  - constraint: unique(slug)
  - constraint: slug length between 1 and 128
  - constraint: display_name length between 1 and 256
  - constraint: keywords is an array of strings; max 64 entries; each entry length between 1 and 64
- `tags.json` — Normalized tag dictionary used to label icons and support search by tag. (18 rows; fields: ['id', 'name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'hidden']
  - constraint: unique(name)
  - constraint: name length between 1 and 64
- `icon_tags.json` — Many-to-many join table connecting icons to tags for searching and browsing. (18 rows; fields: ['id', 'icon_id', 'tag_id', 'source', 'weight', 'created_at', 'updated_at'])
  - lifecycle `source`: ['import', 'curated', 'inferred']
  - constraint: foreign key (icon_id) references icons(id) on delete cascade
  - constraint: foreign key (tag_id) references tags(id) on delete cascade
  - constraint: unique(icon_id, tag_id)
  - constraint: weight >= 0 and weight <= 1
- `icon_aliases.json` — Alternate names/synonyms that should resolve to a canonical icon during search (e.g. 'bell' -> 'notification'). (18 rows; fields: ['id', 'alias', 'icon_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: foreign key (icon_id) references icons(id) on delete cascade
  - constraint: unique(alias)
  - constraint: alias length between 1 and 128
- `platform_guides.json` — Platform-specific usage instructions and snippets for integrating Hugeicons into various ecosystems. (18 rows; fields: ['id', 'platform', 'title', 'content_markdown', 'code_examples', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(platform)
  - constraint: title length between 1 and 200
  - constraint: content_markdown length between 1 and 200000
  - constraint: code_examples is an array; max 50 items

## Business rules enforced by the tools

- Tool list_icons returns icons where status IN ('active','deprecated') and excludes 'hidden' unless an internal/admin flag is used (not exposed by tool surface).
- Tool search_icons requires query to be a non-empty string after trimming; it is split on commas into up to 20 subqueries; each subquery must be 1..128 chars after trimming.
- search_icons matches icons by: (a) icons.slug/display_name ILIKE subquery, (b) icon_aliases.alias ILIKE subquery where alias status='active', (c) tags.name ILIKE subquery joined via icon_tags, and (d) icons.keywords contains token; results are deduplicated by icon_id.
- search_icons only returns icons with status IN ('active','deprecated'); hidden icons never appear.
- get_platform_usage must return exactly one active platform_guides row for the requested platform; if none exists, the tool returns a not-found error.
- Foreign-key integrity: deleting an icon cascades to icon_tags and icon_aliases; deleting a tag cascades to icon_tags.
- Uniqueness: icons.slug, tags.name, icon_aliases.alias, platform_guides.platform must be globally unique.
- Status transition rules must be enforced as declared in each collection lifecycle transitions.