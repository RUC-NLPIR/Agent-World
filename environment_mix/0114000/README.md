# After Effects MCP Server — local MCP environment

This backend models an MCP server that brokers requests from clients to a locally-running After Effects instance. It stores tool invocations (scripts/effects/animation actions), their parameters, execution status, and the last returned results per client session, enabling get-results/help-style reads and auditability of mutations applied to AE projects.

Repository: https://github.com/Dakkshin/after-effects-mcp
Homepage: https://smithery.ai/server/@Dakkshin/after-effects-mcp

## Datastore

- `mcp_clients.json` — Represents a calling MCP client (or integration instance) used for rate limits, auditing and scoping 'last results' to the caller. (18 rows; fields: ['id', 'client_name', 'api_key_hash', 'status', 'rate_limit_rpm', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(client_name)
  - constraint: rate_limit_rpm >= 1
  - constraint: rate_limit_rpm <= 600
- `ae_hosts.json` — A configured After Effects host/bridge target (usually a local machine + AE instance) that can execute scripts/commands. (18 rows; fields: ['id', 'host_label', 'bridge_transport', 'ae_version', 'status', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['online', 'offline', 'degraded', 'disabled']
  - constraint: unique(host_label)
- `tool_invocations.json` — An invocation of any tool in this MCP server, storing the exact parameters, execution outcome, and linkage to the last results per client. (18 rows; fields: ['id', 'client_id', 'ae_host_id', 'tool_name', 'request_params', 'status', 'is_read_only', 'started_at', 'finished_at', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(client_id) references mcp_clients(id) on delete restrict
  - constraint: fk(ae_host_id) references ae_hosts(id) on delete restrict
  - constraint: finished_at is null OR started_at is not null
  - constraint: started_at <= finished_at when both non-null
- `invocation_results.json` — Stores the output payload of a tool invocation (including help text and any structured data returned by AE). Used by get-results to fetch the last successful/last completed output for a client/host. (18 rows; fields: ['id', 'invocation_id', 'client_id', 'ae_host_id', 'result_kind', 'payload', 'is_last_for_client', 'created_at', 'updated_at'])
  - lifecycle `result_kind`: ['script_output', 'help_text', 'effects_help_text', 'bridge_test_report', 'composition_created', 'keyframe_set', 'expression_set', 'effect_applied', 'template_applied', 'generic']
  - constraint: fk(invocation_id) references tool_invocations(id) on delete cascade
  - constraint: fk(client_id) references mcp_clients(id) on delete restrict
  - constraint: fk(ae_host_id) references ae_hosts(id) on delete restrict
  - constraint: payload must be valid JSON object
- `ae_mutation_log.json` — Normalized log of AE state-changing actions derived from tool invocations (composition creation, keyframes, expressions, effects). Supports audit/replay/debug beyond raw invocation params. (18 rows; fields: ['id', 'invocation_id', 'client_id', 'ae_host_id', 'mutation_type', 'comp_index', 'layer_index', 'property_name', 'time_seconds', 'value_json', 'expression_string', 'effect_name', 'effect_match_name', 'effect_category', 'preset_path', 'template_name', 'settings_json', 'composition_spec', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['applied', 'failed']
  - constraint: fk(invocation_id) references tool_invocations(id) on delete cascade
  - constraint: fk(client_id) references mcp_clients(id) on delete restrict
  - constraint: fk(ae_host_id) references ae_hosts(id) on delete restrict
  - constraint: if mutation_type in ('set_layer_keyframe','set_layer_expression','apply_effect','apply_effect_template') then comp_index is not null and comp_index >= 1

## Business rules enforced by the tools

- Every tool call creates exactly one tool_invocations row with tool_name equal to the requested tool and request_params equal to the provided JSON parameters (or {} for parameterless tools).
- Tool invocation status transitions must follow tool_invocations.lifecycle.transitions; terminal states (succeeded/failed/cancelled) cannot transition further.
- The server must validate request_params against the corresponding JSON schema constraints: exclusiveMinimum(0) implies the stored integer/number is > 0; backgroundColor channels must be integers within 0..255; templateName must be one of the enumerated values; operation in test-animation must be 'keyframe' or 'expression'.
- run-script must only execute predefined, allowlisted scripts; tool_invocations.request_params.script must match a configured allowlist entry and tool_invocations.is_read_only must be true for run-script.
- get-help and mcp_aftereffects_get_effects_help return help text without mutating AE; they must store an invocation_results row with result_kind 'help_text' or 'effects_help_text' and payload containing the returned text.
- get-results returns the latest invocation_results row where is_last_for_client=true for the requesting (client_id, ae_host_id). If none exists, it must return an empty/explicit 'no results' payload but still record a tool_invocations row for auditing.
- For every succeeded invocation that produces output, the server must create exactly one invocation_results row with unique(invocation_id) and set is_last_for_client=true; it must also clear any previous last result for the same (client_id, ae_host_id) so the partial uniqueness holds.
- create-composition, setLayerKeyframe, setLayerExpression, apply-effect, apply-effect-template, and their mcp_aftereffects_* aliases are treated as mutating operations; tool_invocations.is_read_only must be false for these tools.
- On successful mutation tools, the server must write an ae_mutation_log row reflecting the normalized parameters (compIndex/layerIndex/propertyName/time/value/expression/effect/template/settings) and set status='applied'; on failure, it must write status='failed' with whatever parameters were validated.
- apply-effect requires at least one of effectName or effectMatchName to be present in request_params; effectSettings/customSettings must be JSON objects when provided.
- Rate limiting is enforced per mcp_clients.rate_limit_rpm: if exceeded, the server must reject the request before creating downstream AE execution, but it should still record a tool_invocations row with status='failed' and error_code='RATE_LIMITED'.
- ae_hosts.status must be 'online' or 'degraded' to run AE-executing tools (all except get-help/get-results/effects help). If not, the invocation must fail with error_code='AE_HOST_UNAVAILABLE'.