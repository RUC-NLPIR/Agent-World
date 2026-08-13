# ennkaheksa — local MCP environment

Ennkaheksa is a read-heavy catalog and validation backend for the n8n ecosystem. It stores a normalized registry of n8n node types (with schemas, docs, and AI-tool metadata), a workflow-template index (including template JSON and node-type usage), and an audit log of validation/documentation requests so the API can power search, lookup, and validation tools consistently.

Repository: https://github.com/kivilaid/n8n-mcp
Homepage: https://smithery.ai/server/@kivilaid/n8n-mcp

## Datastore

- `node_packages.json` — Canonical n8n node packages supported by the service (e.g., n8n-nodes-base, @n8n/n8n-nodes-langchain). Used to constrain list_nodes filters and to compute ecosystem statistics. (12 rows; fields: ['id', 'package_name', 'display_name', 'node_type_prefix', 'status', 'node_count_cached', 'ai_tool_count_cached', 'version', 'source', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: unique(package_name)
  - constraint: node_type_prefix in ('nodes-base','nodes-langchain') for known packages; otherwise non-empty string
  - constraint: node_count_cached >= 0
  - constraint: ai_tool_count_cached >= 0
- `nodes.json` — Registry of n8n node types with searchable metadata, schemas, docs, and AI-tool info. Powers list/search, node info, node docs, property search, dependency analysis, and node validation entry points. (38 rows; fields: ['id', 'package_id', 'node_type', 'node_name', 'display_name', 'description', 'category', 'development_style', 'usable_as_tool', 'is_versioned', 'schema_json', 'essentials_json', 'documentation_markdown', 'doc_coverage', 'tool_usage_markdown', 'property_index', 'dependency_index', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'disabled']
  - constraint: unique(node_type)
  - constraint: foreign key (package_id) references node_packages(id) on update cascade on delete restrict
  - constraint: category in ('trigger','transform','output','input','AI')
  - constraint: development_style in ('declarative','programmatic')
- `task_templates.json` — Curated task-to-node configuration templates used by list_tasks and get_node_for_task. Provides ready-to-use node config stubs for common tasks. (19 rows; fields: ['id', 'task_key', 'category', 'title', 'description', 'recommended_node_type', 'preconfigured_config', 'required_user_inputs', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(task_key)
  - constraint: category in ('HTTP/API','Webhooks','Database','AI/LangChain','Data Processing','Communication')
  - constraint: recommended_node_type must exist in nodes(node_type)
  - constraint: preconfigured_config must be JSON object
- `workflow_templates.json` — Indexed n8n workflow templates (from n8n.io/community) including metadata, full JSON, and task tagging. Supports search_templates, list_node_templates, get_template, and get_templates_for_task. (27 rows; fields: ['id', 'external_template_id', 'name', 'description', 'view_count', 'published_at', 'workflow_json', 'source_url', 'task_tag', 'status', 'last_synced_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: unique(external_template_id)
  - constraint: view_count >= 0
  - constraint: workflow_json must be JSON object
  - constraint: if task_tag is not null then task_tag in allowed enum
- `template_node_types.json` — Join table mapping workflow templates to the node types used inside them. Powers list_node_templates(nodeTypes) efficiently without parsing workflow_json at query time. (30 rows; fields: ['id', 'template_id', 'node_type_ref', 'node_type_canonical', 'count_in_workflow', 'created_at', 'updated_at'])
  - constraint: foreign key (template_id) references workflow_templates(id) on update cascade on delete cascade
  - constraint: unique(template_id, node_type_ref)
  - constraint: count_in_workflow >= 1
- `api_requests.json` — Audit/telemetry of tool calls and validation runs. Enables rate limiting, debugging, and measuring usage of docs/search/validation features without storing any secrets. (31 rows; fields: ['id', 'tool_name', 'request_params', 'response_summary', 'status', 'error_code', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ok', 'error']
  - constraint: duration_ms >= 0
  - constraint: tool_name in ('tools_documentation','list_nodes','get_node_info','search_nodes','list_ai_tools','get_node_documentation','get_database_statistics','get_node_essentials','search_node_properties','get_node_for_task','list_tasks','validate_node_operation','validate_node_minimal','get_property_dependencies','get_node_as_tool_info','list_node_templates','get_template','search_templates','get_templates_for_task','validate_workflow','validate_workflow_connections','validate_workflow_expressions')
  - constraint: request_params must be JSON object

## Business rules enforced by the tools

- list_nodes.limit must be between 1 and 500; search_nodes.limit between 1 and 200; search_templates.limit between 1 and 200; list_node_templates.limit between 1 and 100.
- list_nodes.package, when provided, must match an active node_packages.package_name; otherwise return an error indicating allowed values.
- list_nodes.category, when provided, must be a single value in {trigger, transform, output, input, AI}.
- get_node_info/get_node_essentials/get_node_documentation/search_node_properties/get_property_dependencies/get_node_as_tool_info must error NODE_NOT_FOUND if nodes.node_type does not exist or is not status=active.
- list_ai_tools returns nodes where usable_as_tool=true and status=active.
- search_nodes.query should be tokenized; matching is performed case-insensitively against nodes.node_name, display_name, and description using OR semantics across tokens; results are limited by the provided limit and ordered by a relevance score (exact name match > prefix match > description match).
- search_node_properties(nodeType, query) searches nodes.property_index entries for the given node; it must return at most maxResults (1..200) matches ordered by relevance (path/name exact match > contains match > description match).
- get_property_dependencies(nodeType, config?) must compute visible/hidden sets by evaluating dependency_index conditions against the provided config; if config is omitted, return the raw dependency graph.
- validate_node_minimal must only check presence of required fields derived from nodes.essentials_json (or from schema_json when essentials_json lacks the needed section) and must not emit warnings or suggestions.
- validate_node_operation must validate config against the node schema with the selected profile; profile=minimal checks required fields only; runtime checks critical type/format errors; ai-friendly includes common best-practice warnings; strict includes all checks and best-practice warnings.
- validate_workflow/workflow_connections/workflow_expressions operate purely on the submitted workflow object and must not persist it; only an api_requests audit row is stored.
- validate_workflow.options.validateNodes/validateConnections/validateExpressions default to true/true/true when omitted; validate_workflow.options.profile defaults to runtime.
- get_database_statistics must be derived from nodes and node_packages (total active nodes, usable_as_tool count, triggers count by category, versioned node count, documentation coverage percentage) and must not require any external calls.
- get_template(templateId) resolves workflow_templates.external_template_id; it must error TEMPLATE_NOT_FOUND if not present or status=removed.
- search_templates(query) searches workflow_templates.name and workflow_templates.description only (not template_node_types); matching is case-insensitive and limited by the provided limit.
- list_node_templates(nodeTypes) must treat nodeTypes as an AND filter: returned templates must contain all requested nodeTypes in template_node_types.node_type_ref; results are limited and ordered by view_count desc then recency.
- get_templates_for_task(task) returns workflow_templates where task_tag equals the requested enum value and status=active, ordered by view_count desc.
- Any tool call must write an api_requests row with tool_name, request_params, status, duration_ms; if an error occurs, status=error and error_code must be populated.