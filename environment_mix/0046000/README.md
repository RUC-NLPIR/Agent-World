# PowerShell Exec Server — local MCP environment

This backend stores audited PowerShell execution requests and script-generation jobs initiated via an API, including inputs, timeouts, outputs, and error details. It also maintains reusable script templates and a structured event stream for progress/log reporting tied to each execution, enabling replayable diagnostics and operational governance.

Repository: https://github.com/DynamicEndpoints/PowerShell-Exec-MCP-Server
Homepage: https://smithery.ai/server/@DynamicEndpoints/powershell-exec-mcp-server

## Datastore

- `clients.json` — Represents an MCP client/application identity making tool calls; used for auditing, throttling, and attribution across executions and generated scripts. (12 rows; fields: ['id', 'client_external_id', 'display_name', 'status', 'default_timeout_seconds', 'max_timeout_seconds', 'requests_per_minute_limit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(client_external_id) where client_external_id is not null
  - constraint: default_timeout_seconds between 1 and 300
  - constraint: max_timeout_seconds between 1 and 300
  - constraint: default_timeout_seconds <= max_timeout_seconds
- `powershell_executions.json` — A single execution request of PowerShell code, including system/query tools that are implemented as PowerShell under the hood (system info, processes, services, event logs). Stores normalized inputs plus captured stdout/stderr and exit metadata. (36 rows; fields: ['id', 'client_id', 'request_id', 'tool_name', 'timeout_seconds', 'code', 'arguments', 'status', 'started_at', 'finished_at', 'duration_ms', 'exit_code', 'stdout', 'stderr', 'combined_output', 'error_type', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'timed_out', 'cancelled']
  - constraint: foreign key (client_id) references clients(id) on delete restrict
  - constraint: timeout_seconds between 1 and 300
  - constraint: tool_name in ('run_powershell','run_powershell_with_progress','get_system_info','get_running_services','get_processes','get_event_logs')
  - constraint: code is not null when tool_name in ('run_powershell','run_powershell_with_progress')
- `execution_events.json` — Append-only event stream for a PowerShell execution: log lines, warnings/errors, progress updates, and structured telemetry emitted during run_powershell_with_progress and any tool using MCP context logging. (31 rows; fields: ['id', 'execution_id', 'sequence', 'event_type', 'level', 'message', 'progress_current', 'progress_total', 'payload', 'emitted_at', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['log', 'progress', 'output_chunk', 'state_change']
  - constraint: foreign key (execution_id) references powershell_executions(id) on delete cascade
  - constraint: unique(execution_id, sequence)
  - constraint: sequence >= 1
  - constraint: progress_current is not null and progress_total is not null when event_type = 'progress'
- `script_templates.json` — Stored PowerShell script templates used by generate_script_from_template (and optionally as building blocks for other generators). Templates support parameter substitution and can be versioned. (11 rows; fields: ['id', 'template_name', 'version', 'description', 'content', 'placeholders', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'deleted']
  - constraint: unique(template_name, version)
  - constraint: version >= 1
  - constraint: template_name length between 1 and 128
  - constraint: content length >= 1
- `script_generation_jobs.json` — Tracks script generation requests (template-based and AI/logic-based generators for custom, Intune, and BigFix scripts), including parameters, output location request, and generated content. Can create one or more artifacts per job (e.g., script pair). (28 rows; fields: ['id', 'client_id', 'request_id', 'tool_name', 'status', 'timeout_seconds', 'template_id', 'template_name', 'description', 'script_type', 'include_logging', 'include_error_handling', 'logic_detection', 'logic_remediation', 'logic_relevance', 'logic_action', 'parameters_object', 'parameters_list', 'requested_output_path', 'requested_output_dir', 'resolved_output_paths', 'generated_primary_content', 'generated_secondary_content', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key (client_id) references clients(id) on delete restrict
  - constraint: foreign key (template_id) references script_templates(id) on delete restrict
  - constraint: timeout_seconds between 1 and 300
  - constraint: tool_name in ('generate_script_from_template','generate_custom_script','generate_intune_remediation_script','generate_intune_script_pair','generate_bigfix_relevance_script','generate_bigfix_action_script','generate_bigfix_script_pair','ensure_directory')

## Business rules enforced by the tools

- For any tool call, the effective timeout_seconds MUST be clamped to [1, 300] and MUST NOT exceed clients.max_timeout_seconds; if omitted/null, use clients.default_timeout_seconds.
- clients.status MUST be 'active' to create powershell_executions or script_generation_jobs; otherwise the server MUST reject the request.
- run_powershell and run_powershell_with_progress MUST persist the supplied 'code' verbatim in powershell_executions.code and mark tool_name accordingly.
- get_system_info, get_running_services, get_processes, and get_event_logs MUST persist their request parameters in powershell_executions.arguments (including nulls omitted) and MUST enforce per-parameter validation (level in 1..4; newest >= 1; top >= 1).
- powershell_executions.status transitions MUST follow the declared lifecycle; any attempt to write an invalid transition MUST be rejected.
- When powershell_executions.status becomes 'running', started_at MUST be set; when it becomes a terminal state (succeeded/failed/timed_out/cancelled), finished_at and duration_ms MUST be set.
- execution_events MUST be append-only: updates are only allowed to corrected payload fields and MUST NOT change execution_id or sequence; sequence MUST be strictly increasing per execution.
- run_powershell_with_progress MUST emit at least one execution_events record of event_type='progress' OR a sequence of 'log' events if ctx is provided; otherwise no ctx-derived events are required.
- generate_script_from_template MUST resolve template_name to an active script_templates row; if multiple versions exist, the highest version with status='active' MUST be used unless a specific template_id is set internally.
- generate_script_from_template MUST validate that every key in parameters_object exists in script_templates.placeholders (extra keys rejected) and that all required placeholders are provided (missing keys rejected).
- For ensure_directory, script_generation_jobs.tool_name MUST be 'ensure_directory' and requested_output_path MUST contain the requested 'path'; the server MUST store the resolved absolute path in resolved_output_paths[0].
- If a script generation tool writes to disk (requested_output_path/output_dir provided), the server MUST store the final resolved paths in resolved_output_paths and MUST ensure they are under an allowed base directory (path traversal attempts rejected).
- For script pair generators (generate_intune_script_pair, generate_bigfix_script_pair), both generated_primary_content and generated_secondary_content MUST be set on success; for single script generators, generated_secondary_content MUST be null.
- Error fields (error_message, error_type, stderr) MUST be null on success and MUST be populated on failed/timed_out where applicable.