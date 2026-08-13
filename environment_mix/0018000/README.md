# Pickapicon MCP — local MCP environment

This backend stores icon repositories (icon sets), the icons within them, and per-icon assets/metadata needed to return detailed icon information by prefix and name. The primary workflows are: list available icon repos, search/browse icons by description/prefix, and fetch a single icon's full detail (including SVG) by (prefix, name).

Repository: https://github.com/Leee62/pickapicon-mcp
Homepage: https://smithery.ai/server/@Leee62/pickapicon-mcp

## Datastore

- `icon_repositories.json` — Catalog of supported icon repositories/sets (e.g., ant-design) addressable by a unique prefix. (30 rows; fields: ['id', 'prefix', 'display_name', 'description', 'homepage_url', 'source_repo_url', 'license', 'version', 'icon_count', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(prefix)
  - constraint: icon_count >= 0
  - constraint: prefix length between 1 and 64
  - constraint: status in ('active','disabled','deleted')
- `icons.json` — Individual icon records keyed by (repo_prefix, icon_name). Stores searchable metadata for description-based queries. (18 rows; fields: ['id', 'repo_id', 'prefix', 'name', 'description', 'tags', 'categories', 'deprecated', 'popularity_score', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: foreign key(repo_id) references icon_repositories(id) on update cascade on delete restrict
  - constraint: unique(repo_id, name)
  - constraint: unique(prefix, name)
  - constraint: popularity_score between 0 and 1
- `icon_assets.json` — Per-icon asset payloads (SVG and derived metadata). Supports returning detailed icon info by prefix and name. (18 rows; fields: ['id', 'icon_id', 'asset_type', 'svg_body', 'view_box', 'width', 'height', 'content_hash', 'byte_size', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key(icon_id) references icons(id) on update cascade on delete cascade
  - constraint: unique(icon_id, asset_type)
  - constraint: byte_size >= 0
  - constraint: width is null or width > 0

## Business rules enforced by the tools

- Tool get_icon_repos returns icon_repositories where status='active', ordered by display_name asc (or prefix asc) and must include prefix and display_name at minimum.
- Tool get_icons_by_desc_and_prefix filters icons by status='active' and repository status='active'. If a prefix is provided by the caller/context, it must match icon_repositories.prefix and be used to filter icons.prefix=prefix; if a description is provided, it performs a case-insensitive partial match against icons.description and optionally icons.tags (e.g., SQL ILIKE '%desc%').
- Tool get_icon_detail_by_prefix_and_name must resolve exactly one icon by (icons.prefix, icons.name) with icons.status='active' and repository status='active'; if not found, return a not-found error.
- When serving icon detail, the implementation must return the active svg asset from icon_assets where icon_id=icons.id and asset_type='svg' and status='active'; if missing, the icon is considered incomplete and the API should return not-found or a 409/422 depending on service conventions.
- icons.prefix must always equal icon_repositories.prefix for the referenced repo_id; writes/imports must enforce this invariant (either via application logic or a database constraint/trigger).
- A repository cannot be deleted if there exist non-deleted icons referencing it unless the delete operation first transitions those icons to deleted (enforced by FK delete restrict plus application-side lifecycle transitions).
- Uniqueness must be enforced so that (prefix, name) identifies a single icon globally, enabling deterministic get_icon_detail_by_prefix_and_name behavior.
- Search results must never include entities with status in ('disabled','deleted') even if they still exist for audit/history.