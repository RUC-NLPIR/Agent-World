# OSINT Server — local MCP environment

This backend stores OSINT investigations submitted via an API and the executed tool runs (whois, nmap, dnsrecon, dnstwist, dig, host) along with their outputs. The main workflow is: an API client creates/runs an investigation against a target, the system executes one or more OSINT tools, persists normalized metadata plus raw outputs, and optionally aggregates a multi-tool overview report.

Repository: https://github.com/himanshusanecha/mcp-osint-server
Homepage: https://smithery.ai/server/@himanshusanecha/mcp-osint-server

## Datastore

- `api_clients.json` — Represents authenticated callers of the OSINT Server (e.g., API keys/clients). Used to attribute investigations, enforce quotas, and audit usage. (20 rows; fields: ['id', 'name', 'api_key_hash', 'status', 'requests_per_minute_limit', 'daily_investigation_limit', 'daily_tool_run_limit', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(api_key_hash)
  - constraint: unique(name)
  - constraint: requests_per_minute_limit between 1 and 6000
  - constraint: daily_investigation_limit between 0 and 100000
- `investigations.json` — Top-level OSINT requests against a target (domain/IP/hostname). Used by osint_overview and to group individual tool runs. (17 rows; fields: ['id', 'client_id', 'target', 'target_type', 'canonical_domain', 'status', 'error_message', 'requested_toolset', 'started_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'completed', 'failed', 'cancelled']
  - constraint: fk(client_id) references api_clients(id) on delete restrict
  - constraint: target length between 1 and 2048
  - constraint: canonical_domain is null or length between 1 and 253
  - constraint: status in ('queued','running','completed','failed','cancelled')
- `tool_runs.json` — An execution record for a single OSINT tool against a single target/domain as invoked by the API tools. (17 rows; fields: ['id', 'client_id', 'investigation_id', 'tool_name', 'input_target', 'input_domain', 'status', 'exit_code', 'error_message', 'duration_ms', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'timed_out', 'cancelled']
  - constraint: fk(client_id) references api_clients(id) on delete restrict
  - constraint: fk(investigation_id) references investigations(id) on delete set null
  - constraint: tool_name in ('whois_lookup','nmap_scan','dnsrecon_lookup','dnstwist_lookup','dig_lookup','host_lookup','osint_overview')
  - constraint: ((tool_name = 'dnstwist_lookup' and input_domain is not null and input_target is null) or (tool_name != 'dnstwist_lookup' and input_target is not null))
- `tool_run_artifacts.json` — Persisted outputs from tool runs, including raw stdout/stderr and parsed structured findings. (18 rows; fields: ['id', 'tool_run_id', 'artifact_type', 'content_text', 'content_json', 'content_sha256', 'bytes', 'redacted', 'created_at', 'updated_at'])
  - lifecycle `artifact_type`: ['stdout', 'stderr', 'raw_json', 'parsed_summary', 'scan_results', 'dns_records', 'whois_record', 'host_resolution', 'dnstwist_permutations', 'overview_report']
  - constraint: fk(tool_run_id) references tool_runs(id) on delete cascade
  - constraint: bytes between 0 and 10485760
  - constraint: content_text is not null or content_json is not null
  - constraint: content_sha256 is null or length(content_sha256) = 64
- `usage_events.json` — Append-only ledger of billable/quotable events for rate limiting, daily quotas, and audit (per investigation/tool run). (18 rows; fields: ['id', 'client_id', 'event_type', 'investigation_id', 'tool_run_id', 'tool_name', 'occurred_at', 'meta', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['investigation_created', 'tool_run_created', 'tool_run_completed', 'tool_run_failed']
  - constraint: fk(client_id) references api_clients(id) on delete restrict
  - constraint: fk(investigation_id) references investigations(id) on delete set null
  - constraint: fk(tool_run_id) references tool_runs(id) on delete set null
  - constraint: occurred_at <= created_at + interval '5 minutes'

## Business rules enforced by the tools

- Each tool invocation (whois_lookup, nmap_scan, dnsrecon_lookup, dig_lookup, host_lookup) must create exactly one tool_runs row with tool_name set accordingly and input_target = parameters.target.
- Each dnstwist_lookup invocation must create exactly one tool_runs row with tool_name='dnstwist_lookup' and input_domain = parameters.domain (and input_target must be NULL).
- Each osint_overview invocation must create one investigations row and one parent tool_runs row with tool_name='osint_overview', then create child tool_runs rows for each requested tool in investigations.requested_toolset (or the default set if empty).
- A tool_runs row may only transition status according to tool_runs.lifecycle.transitions; once in a terminal state (succeeded/failed/timed_out/cancelled) it must not change status again.
- When a tool run reaches a terminal state, finished_at and duration_ms must be set; started_at must be set when status transitions to running.
- For each tool run, the system must store at least one artifact in tool_run_artifacts (typically stdout and/or raw_json); artifacts must obey unique(tool_run_id, artifact_type).
- API clients with status != 'active' must be rejected from creating investigations or tool runs.
- Rate limiting: requests per minute for a client must not exceed api_clients.requests_per_minute_limit based on usage_events occurred_at timestamps.
- Daily quotas: within any rolling 24-hour window, counts of investigations_created and tool_run_created for a client must not exceed daily_investigation_limit and daily_tool_run_limit respectively.
- Targets must be validated as non-empty strings; canonical_domain must be derived when possible (e.g., from URL/hostname) and used as the input to dnstwist when osint_overview includes dnstwist_lookup.
- Data retention: tool_run_artifacts.bytes must not exceed 10MB per artifact; oversized outputs must be truncated and marked redacted=true with a note in content_json or content_text.
- FK integrity must be enforced: deleting a tool_run must cascade-delete its artifacts; deleting an investigation must not delete tool_runs but should set tool_runs.investigation_id to NULL (preserve audit).