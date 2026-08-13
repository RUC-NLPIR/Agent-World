# shadcn/ui Component Reference Server — local MCP environment

This backend stores a curated, versioned catalog of shadcn/ui components, their documentation (descriptions, props, installation notes), and runnable usage examples. It also records search queries for basic analytics/rate limiting and supports keyword search over component metadata and example text.

Repository: https://github.com/ymadd/shadcn-ui-mcp-server
Homepage: https://smithery.ai/server/@ymadd/shadcn-ui-mcp-server

## Datastore

- `components.json` — Canonical registry of shadcn/ui components and their high-level metadata used for listing, lookup by name, and search indexing. (32 rows; fields: ['id', 'slug', 'display_name', 'summary', 'category', 'tags', 'source_url', 'shadcn_version', 'search_text', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'hidden']
  - constraint: unique(slug)
  - constraint: length(slug) between 2 and 64
  - constraint: status in ('active','deprecated','hidden')
  - constraint: search_text is not null
- `component_details.json` — Detailed documentation for a component (long description, install/use notes, props API). One active revision per component. (34 rows; fields: ['id', 'component_id', 'revision', 'description_md', 'installation_md', 'usage_md', 'props_schema', 'dependencies', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'active', 'superseded']
  - constraint: foreign key(component_id) references components(id) on delete cascade
  - constraint: revision >= 1
  - constraint: unique(component_id, revision)
  - constraint: at most one active details per component_id (partial unique: unique(component_id) where status='active')
- `component_examples.json` — Code examples/snippets associated with a component, used by get_component_examples and included in search indexing. (36 rows; fields: ['id', 'component_id', 'title', 'description', 'language', 'code', 'sort_order', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'hidden']
  - constraint: foreign key(component_id) references components(id) on delete cascade
  - constraint: sort_order >= 0
  - constraint: unique(component_id, sort_order)
  - constraint: language in ('tsx','jsx','ts','js','md')
- `search_queries.json` — Audit/analytics log of search_components requests and their computed results. (35 rows; fields: ['id', 'query_text', 'normalized_query', 'matched_component_ids', 'result_count', 'match_strategy', 'request_source', 'created_at', 'updated_at'])
  - lifecycle `match_strategy`: ['fts', 'like', 'tag']
  - constraint: length(query_text) between 1 and 256
  - constraint: normalized_query = lower(trim(query_text)) (enforced in application or generated column)
  - constraint: result_count >= 0
  - constraint: result_count = array_length(matched_component_ids)

## Business rules enforced by the tools

- list_shadcn_components returns components where status != 'hidden', ordered by display_name asc; the response is derived from components.slug and components.display_name plus optional summary/category/tags.
- get_component_details requires an existing components.slug = componentName with components.status != 'hidden' and returns the single component_details row where component_id matches and status='active'. If none exists, the tool must return a not-found error.
- get_component_examples requires an existing components.slug = componentName with components.status != 'hidden' and returns component_examples rows where component_id matches and status='active', ordered by sort_order asc.
- search_components requires query length 1..256; it matches against components.search_text and components.tags (and may additionally match display_name/slug), excluding components.status='hidden'.
- search_components must write a search_queries row for each request, including normalized_query, ordered matched_component_ids, result_count, and match_strategy; updated_at must equal created_at for this immutable log.
- Any update that changes component_details.description_md, component_details.props_schema, or component_examples.code must trigger recomputation of components.search_text for the associated component within the same transaction or via a guaranteed background job.
- Only one component_details row may be status='active' per component; promoting a draft to active must atomically mark the previously active revision (if any) as superseded.
- Foreign key integrity: deleting a component cascades to its details and examples; hidden components must not be returned by any read tool.