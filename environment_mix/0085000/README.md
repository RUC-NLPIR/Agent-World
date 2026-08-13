# Pentest MCP — local MCP environment

Pentest MCP orchestrates offensive-security helper actions (network/service enumeration, web content discovery, vulnerability scanning, wordlist generation, and password hash cracking) and stores their inputs, execution state, and results. Users (or API keys) operate in a selected mode (student/professional), create tool runs (scans/jobs), may cancel running scans, and can compile multiple scan results into a client-facing assessment report.

Repository: https://github.com/DMontgomery40/pentest-mcp
Homepage: https://smithery.ai/server/@DMontgomery40/pentest-mcp

## Datastore

- `principals.json` — Identities invoking the MCP tools (interactive user, service integration, or API key holder). Stores the effective operating mode used for safety/guardrails and auditing. (18 rows; fields: ['id', 'display_name', 'kind', 'default_mode', 'status', 'last_mode_changed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended']
  - constraint: default_mode in ('student','professional')
  - constraint: status in ('active','suspended')
  - constraint: created_at <= updated_at
- `tool_runs.json` — All executions of tools (nmapScan, gobuster, nikto, generateWordlist, runJohnTheRipper). Stores request parameters, execution status, cancellation, and output artifacts/summary. (19 rows; fields: ['id', 'principal_id', 'tool', 'mode_effective', 'status', 'cancel_requested_at', 'started_at', 'finished_at', 'exit_code', 'error_message', 'request_params', 'result_summary', 'stdout_text', 'stderr_text', 'raw_output_ref', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancel_requested', 'cancelled']
  - constraint: fk(principal_id) references principals(id) on delete restrict
  - constraint: tool in ('nmapScan','gobuster','nikto','generateWordlist','runJohnTheRipper')
  - constraint: mode_effective in ('student','professional')
  - constraint: status in ('queued','running','succeeded','failed','cancel_requested','cancelled')
- `scan_findings.json` — Structured findings extracted from tool outputs (especially nikto, nmap scripts, and gobuster hits) to support reporting. Each finding belongs to a single tool_run and can be included in client reports. (18 rows; fields: ['id', 'tool_run_id', 'kind', 'severity', 'title', 'details', 'evidence_text', 'created_at', 'updated_at'])
  - lifecycle `severity`: ['info', 'low', 'medium', 'high', 'critical']
  - constraint: fk(tool_run_id) references tool_runs(id) on delete cascade
  - constraint: severity in ('info','low','medium','high','critical')
  - constraint: kind in ('open_port','service','os_guess','web_path','vulnerability','informational','credential_cracked')
  - constraint: unique(tool_run_id, kind, title) where kind in ('open_port','web_path') is false (duplicates allowed), but enforce dedupe at ingest when possible
- `client_reports.json` — Client-facing assessment reports created from a set of scan/tool runs. Stores narrative fields and derived metadata for later retrieval/export. (18 rows; fields: ['id', 'principal_id', 'client', 'title', 'assessment_type', 'summary', 'recommendations', 'status', 'rendered_output_ref', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'finalized']
  - constraint: fk(principal_id) references principals(id) on delete restrict
  - constraint: status in ('draft','finalized')
  - constraint: title length between 1 and 200
  - constraint: client length between 1 and 200
- `client_report_scans.json` — Join table mapping client reports to included scan/tool runs. This is the persistence of createClientReport.scanIds. (18 rows; fields: ['id', 'client_report_id', 'tool_run_id', 'position', 'created_at', 'updated_at'])
  - lifecycle `position`: []
  - constraint: fk(client_report_id) references client_reports(id) on delete cascade
  - constraint: fk(tool_run_id) references tool_runs(id) on delete restrict
  - constraint: unique(client_report_id, tool_run_id)
  - constraint: unique(client_report_id, position)

## Business rules enforced by the tools

- setMode(mode) updates principals.default_mode and principals.last_mode_changed_at for the calling principal; only allowed when principals.status = 'active'.
- nmapScan: tool_runs.tool='nmapScan' and tool_runs.request_params must contain target and may contain ports, fastScan, topPorts, scanTechnique, udpScan, serviceVersionDetection, versionIntensity, osDetection, defaultScripts, scripts, scriptArgs, timingTemplate, skipHostDiscovery, verbose, rawOptions, userModeHint. request_params.target must be a non-empty string.
- nmapScan validation: if request_params.topPorts is provided it must be between 1 and 65535; if request_params.versionIntensity is provided it must be between 0 and 9; if request_params.timingTemplate is provided it must be one of T0..T5; if request_params.scanTechnique is provided it must be one of the enumerated techniques.
- nmapScan mode selection: if request_params.userModeHint is provided, tool_runs.mode_effective MUST equal userModeHint unless server policy forbids elevation; if forbidding, mode_effective stays at principals.default_mode and the run must record a policy note in tool_runs.error_message or result_summary.
- gobuster: tool_runs.tool='gobuster' and request_params must contain target and wordlist. target must be a valid absolute URI string. If threads is provided it must be > 0.
- nikto: tool_runs.tool='nikto' and request_params must contain target (absolute URI). If timeout is provided it must be between 1 and 3600 seconds.
- generateWordlist: tool_runs.tool='generateWordlist' and request_params must contain baseWords as a non-empty array of strings. If minYear/maxYear provided: 1900 <= minYear <= maxYear <= (current_year + 1). includeLeet default false; caseVariations default true.
- runJohnTheRipper: tool_runs.tool='runJohnTheRipper' and request_params must contain hashData as a non-empty string. options, if present, must be an array of strings with length <= 200.
- cancelScan(scanId): scanId must reference an existing tool_runs.id. If tool_runs.status in ('queued','running'), set status='cancel_requested' (or directly 'cancelled' if not yet started) and set cancel_requested_at; if status in terminal states ('succeeded','failed','cancelled'), cancellation is a no-op and must not change finished_at.
- createClientReport: creates client_reports row and client_report_scans rows for each scanId in order. All scanIds must exist in tool_runs and must be owned by the same principal_id as the report creator (or be explicitly shareable by policy; default is same principal only).
- createClientReport requires scanIds array length between 1 and 100; duplicates are rejected (enforced by unique(client_report_id, tool_run_id)).
- Reports may include tool_runs in any status, but when client_reports.status transitions to 'finalized', the backend must snapshot or render outputs (set rendered_output_ref) and prevent further edits to narrative fields and report-scan membership.
- Any ingestion of structured scan_findings must only occur for tool_runs that are in status 'running' or a terminal state; once tool_runs.status is terminal, findings are append-only (updates allowed only to normalize severity/title, tracked by updated_at).
- FK integrity: deleting a client_report cascades to client_report_scans; deleting a tool_run is generally disallowed in production (restrict) to preserve auditability; if allowed in admin mode, it must cascade to scan_findings.