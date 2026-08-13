# Burpsuite Server — local MCP environment

This backend stores BurpSuite-driven scanning activity and the artifacts produced during security testing: scan jobs, detected issues, captured proxy traffic, and the discovered site map. The main workflows are: create a scan against a target URL, poll its status, retrieve issues filtered by severity, and browse proxy history/site map with common filters and limits.

Repository: https://github.com/Cyreslab-AI/burpsuite-mcp-server
Homepage: https://smithery.ai/server/@Cyreslab-AI/burpsuite-mcp-server

## Datastore

- `scans.json` — Vulnerability scan jobs initiated against a target URL, including lifecycle state and execution metadata needed to power start_scan and get_scan_status. (18 rows; fields: ['id', 'target_url', 'scan_type', 'status', 'progress_pct', 'started_at', 'completed_at', 'burp_task_ref', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'completed', 'failed', 'cancelled']
  - constraint: required(target_url)
  - constraint: scan_type in ('passive','active','full')
  - constraint: status in ('queued','running','completed','failed','cancelled')
  - constraint: progress_pct between 0 and 100
- `scan_issues.json` — Vulnerability findings produced by a scan, queryable by scan_id and filterable by severity for get_scan_issues. (19 rows; fields: ['id', 'scan_id', 'severity', 'confidence', 'issue_type', 'title', 'description', 'host', 'url', 'path', 'evidence', 'remediation', 'burp_issue_ref', 'first_seen_at', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `severity`: ['high', 'medium', 'low', 'info']
  - constraint: fk(scan_id) references scans(id) on delete cascade
  - constraint: severity in ('high','medium','low','info')
  - constraint: confidence in ('certain','firm','tentative') or confidence is null
  - constraint: unique(scan_id, burp_issue_ref) where burp_issue_ref is not null
- `proxy_history.json` — HTTP/HTTPS messages captured by Burp Proxy, filterable by host/method/status_code and limit for get_proxy_history. (19 rows; fields: ['id', 'host', 'port', 'scheme', 'method', 'url', 'path', 'status_code', 'request_headers', 'request_body', 'response_headers', 'response_body', 'mime_type', 'request_bytes', 'response_bytes', 'captured_at', 'created_at', 'updated_at'])
  - lifecycle `scheme`: ['http', 'https']
  - constraint: method length between 1 and 16
  - constraint: status_code between 100 and 599 or status_code is null
  - constraint: port between 1 and 65535 or port is null
  - constraint: scheme in ('http','https') or scheme is null
- `site_map_nodes.json` — Discovered site structure (URLs/endpoints) from scanning and browsing, filterable by host/with_parameters/limit for get_site_map. (18 rows; fields: ['id', 'host', 'scheme', 'url', 'path', 'has_parameters', 'parameters', 'discovery_source', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `discovery_source`: ['proxy', 'scan', 'crawler', 'manual']
  - constraint: unique(host, url)
  - constraint: has_parameters = true implies (parameters is not null)
  - constraint: url length <= 2048
  - constraint: scheme in ('http','https') or scheme is null
- `scan_targets.json` — Normalized host/scope records derived from scan target URLs; supports operational constraints like de-duplication, scope tracking, and cross-linking scans to discovered artifacts. (18 rows; fields: ['id', 'canonical_target_url', 'host', 'in_scope', 'last_scanned_at', 'created_at', 'updated_at'])
  - lifecycle `in_scope`: ['true', 'false']
  - constraint: unique(canonical_target_url)
  - constraint: canonical_target_url length <= 2048
  - constraint: index(host)

## Business rules enforced by the tools

- start_scan(target, scan_type) creates a scans row with target_url=target, scan_type defaulting to 'full' when omitted, status='queued', progress_pct=0, created_at/updated_at set to now; it also upserts scan_targets by canonical_target_url and sets scan_targets.last_scanned_at when the scan enters 'running'.
- get_scan_status(scan_id) must return the scans row by primary key; if not found, return a not-found error.
- get_scan_issues(scan_id, severity) must only return scan_issues where scan_id matches; if severity != 'all', filter by scan_issues.severity; severity='all' returns all severities.
- get_proxy_history(host, method, status_code, limit) queries proxy_history ordered by captured_at desc, applying filters when provided; limit defaults to 10 and must be clamped to 1..200.
- get_site_map(host, with_parameters, limit) queries site_map_nodes ordered by last_seen_at desc, applying host filter when provided; when with_parameters=true, filter has_parameters=true; limit defaults to 20 and must be clamped to 1..500.
- FK integrity: scan_issues.scan_id must reference scans.id; deleting a scan must cascade-delete its scan_issues.
- Scan status transitions must follow the transitions map; setting status to 'completed','failed', or 'cancelled' must set completed_at and freeze progress_pct at 100 for completed, or <= 100 for failed/cancelled.
- Severity values accepted by get_scan_issues filter are exactly {'high','medium','low','info','all'}; any other value is rejected.
- status_code filters must be integers in [100, 599]; non-integers are rejected even if the tool schema marks it as number.
- Data retention/quota: proxy_history.response_body and request_body may be truncated to a configured maximum size per record (e.g., 1MB) and older records may be purged after a retention window without affecting scans or issues.