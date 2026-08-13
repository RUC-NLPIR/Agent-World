# Magic UI Component Server — local MCP environment

This backend stores a catalog of Magic UI components and the versioned implementation payloads returned by the API tools. The main workflows are: (1) list all available components, and (2) fetch curated bundles of implementation details by category (layout, media, motion, text, buttons, effects, widgets, backgrounds, devices) tied to a specific catalog release/version.

Repository: https://github.com/magicuidesign/mcp
Homepage: https://smithery.ai/server/@magicuidesign/mcp

## Datastore

- `catalog_releases.json` — Immutable release markers for the component catalog (often aligned to a git tag/commit). Tools read from the currently active release to ensure consistent results across categories. (12 rows; fields: ['id', 'version', 'source_repo_url', 'source_ref', 'is_active', 'published_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'published', 'deprecated']
  - constraint: unique(version)
  - constraint: unique(source_ref)
  - constraint: is_active implies status = 'published'
  - constraint: at_most_one_active_release (partial unique where is_active = true)
- `component_categories.json` — Controlled vocabulary for Magic UI component groupings used by the tool surface (layout, media, motion, text_reveal, text_effects, buttons, effects, widgets, backgrounds, devices). (12 rows; fields: ['id', 'key', 'display_name', 'description', 'sort_order', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: unique(key)
  - constraint: sort_order >= 0
- `components.json` — Canonical registry of Magic UI components (one row per component slug), independent of versioned implementation content. (32 rows; fields: ['id', 'slug', 'display_name', 'summary', 'doc_url', 'repo_path', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'hidden']
  - constraint: unique(slug)
  - constraint: slug matches ^[a-z0-9]+(?:-[a-z0-9]+)*$
- `component_category_memberships.json` — Join table mapping components to one or more categories for grouping and tool responses. (29 rows; fields: ['id', 'component_id', 'category_id', 'is_primary', 'sort_order', 'created_at', 'updated_at'])
  - lifecycle `is_primary`: [True, False]
  - constraint: unique(component_id, category_id)
  - constraint: sort_order >= 0
  - constraint: fk(component_id) references components(id) on delete cascade
  - constraint: fk(category_id) references component_categories(id) on delete restrict
- `component_implementations.json` — Versioned implementation payloads for each component. This is what category tools return (code, instructions, dependencies, and metadata) for the currently active catalog release. (32 rows; fields: ['id', 'release_id', 'component_id', 'language', 'framework', 'runtime_requirements', 'dependencies', 'files', 'usage_instructions', 'examples', 'checksum_sha256', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded', 'removed']
  - constraint: unique(release_id, component_id, framework, language)
  - constraint: fk(release_id) references catalog_releases(id) on delete restrict
  - constraint: fk(component_id) references components(id) on delete cascade
  - constraint: json_schema(files) requires each item to include path:string, content:string, type in ['source','style','asset','config','doc']

## Business rules enforced by the tools

- All read tools (getLayout/getMedia/getMotion/getTextReveal/getTextEffects/getButtons/getEffects/getWidgets/getBackgrounds/getDevices) MUST return implementations from the single active catalog_releases row where is_active = true and status = 'published'.
- getUIComponents MUST list all components with status != 'hidden', and SHOULD include their categories via component_category_memberships joined to component_categories where component_categories.status = 'active'.
- Each category tool MUST return only components that are members of the corresponding component_categories.key via component_category_memberships, and for each component MUST select at most one implementation per (framework, language) from the active release where component_implementations.status = 'active'.
- A catalog_releases row cannot be set to is_active = true unless its status is 'published' and there exists at least one active component_implementations row for that release.
- For any given component_id, at most one component_category_memberships row may have is_primary = true.
- components.slug MUST be globally unique and immutable once referenced by any component_implementations row.
- Deleting a component MUST cascade delete its component_category_memberships and component_implementations; deleting a category MUST be restricted if any memberships exist.
- If a component is set to status = 'deprecated', it may still be returned by tools, but its implementations MUST remain status = 'active' to be included; if a component is status = 'hidden', it MUST NOT be returned by getUIComponents or any category tool.