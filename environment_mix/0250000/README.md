# Shadcn Vue MCP Server — local MCP environment

This backend supports an MCP server that helps users design and generate shadcn-vue UI components: it structures natural-language requirements, filters relevant component candidates, retrieves per-component usage docs/snippets, and runs automated quality checks on generated Vue code. The main workflow persists user tool runs, a canonical component catalog with docs/snippets, and quality-check reports tied to the generated code artifacts.

Repository: https://github.com/HelloGGX/shadcn-vue-mcp
Homepage: https://smithery.ai/server/@HelloGGX/shadcn-vue-mcp

## Datastore

- `workspaces.json` — Tenant boundary for projects using the Shadcn Vue MCP server; used for isolation, rate limiting, and auditability of tool runs and artifacts. (12 rows; fields: ['id', 'slug', 'name', 'status', 'default_icon_module', 'daily_run_quota', 'daily_token_quota', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(slug)
  - constraint: daily_run_quota >= 0
  - constraint: daily_token_quota >= 0
  - constraint: default_icon_module in ('@nuxt/icon','lucide')
- `component_catalog.json` — Canonical catalog of available shadcn-vue UI components and charts, including their usage documentation and reusable code snippet used by component-builder. (38 rows; fields: ['id', 'component_type', 'name', 'display_name', 'tags', 'tailwind_required', 'shadcn_source', 'usage_doc_md', 'snippet_text', 'snippet_version', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: unique(component_type, name)
  - constraint: name = lower(name)
  - constraint: component_type in ('components','charts')
  - constraint: snippet_version <> ''
- `tool_runs.json` — Audit log and persistence for each MCP tool invocation, including inputs/outputs, status, and linkage between successive steps (requirement -> filter -> builder -> check). (35 rows; fields: ['id', 'workspace_id', 'tool_name', 'status', 'request_message', 'request_type', 'request_name', 'request_icon_module', 'request_components_json', 'request_charts_json', 'request_component_code', 'response_text', 'response_json', 'parent_run_id', 'error_code', 'error_message', 'token_estimate_in', 'token_estimate_out', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key (parent_run_id) references tool_runs(id) on delete set null
  - constraint: token_estimate_in >= 0
  - constraint: token_estimate_out >= 0
- `run_selected_items.json` — Normalized list of components/charts selected by components-filter and used by component-builder, including necessity and justification per item. (35 rows; fields: ['id', 'workspace_id', 'filter_run_id', 'builder_run_id', 'catalog_id', 'item_type', 'name', 'necessity', 'justification', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['proposed', 'accepted', 'rejected', 'consumed']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key (filter_run_id) references tool_runs(id) on delete cascade
  - constraint: foreign key (builder_run_id) references tool_runs(id) on delete set null
  - constraint: foreign key (catalog_id) references component_catalog(id) on delete set null
- `generated_artifacts.json` — Stores code artifacts produced/assembled from component-builder snippets and the results from component-quality-check, enabling traceability from requirement to generated Vue code. (43 rows; fields: ['id', 'workspace_id', 'builder_run_id', 'quality_run_id', 'icon_module', 'component_code', 'quality_score', 'quality_feedback', 'quality_issues_json', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'checked', 'approved', 'archived']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key (builder_run_id) references tool_runs(id) on delete restrict
  - constraint: foreign key (quality_run_id) references tool_runs(id) on delete set null
  - constraint: icon_module in ('@nuxt/icon','lucide')

## Business rules enforced by the tools

- A tool run must belong to an active workspace; if workspace.status != 'active', new tool_runs are rejected with error_code='workspace_inactive'.
- Quota enforcement: for each workspace, the number of tool_runs created per UTC day must be <= workspaces.daily_run_quota; otherwise creation is rejected with error_code='quota_runs_exceeded'.
- Quota enforcement: sum(token_estimate_in + token_estimate_out) per workspace per UTC day must be <= workspaces.daily_token_quota; otherwise creation is rejected with error_code='quota_tokens_exceeded'.
- requirement-structuring and components-filter runs must store request_message and must not set request_component_code/request_name/request_type.
- component-usage-doc runs must set request_type in {'components','charts'} and request_name (lowercase); the response must be sourced from component_catalog where (component_type=request_type and name=request_name and status in {'active','deprecated'}), otherwise fail with error_code='component_not_found'.
- components-filter outputs, when structured, must be persisted either in tool_runs.response_json and/or normalized into run_selected_items rows tied to filter_run_id; each (filter_run_id,item_type,name) may appear at most once.
- component-builder runs must include both request_components_json and request_charts_json arrays; each array item must include name, necessity in {'critical','important','optional'}, and justification; invalid items fail validation with error_code='invalid_builder_payload'.
- When a component-builder run succeeds, the system may create a generated_artifacts row with status='draft' and icon_module resolved from request_icon_module or workspace.default_icon_module.
- component-quality-check runs must provide request_component_code; on success, a generated_artifacts row linked by quality_run_id must be updated with quality_feedback/quality_issues_json and transitioned to status='checked'.
- Lifecycle enforcement: tool_runs.status transitions must follow the declared transition map; attempts to update status outside allowed transitions are rejected.
- Catalog integrity: component_catalog.name must be lowercase and unique per component_type; disabled catalog entries must never be returned by component-usage-doc or used to auto-link run_selected_items.catalog_id.