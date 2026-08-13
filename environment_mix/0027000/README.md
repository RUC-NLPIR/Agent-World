# MCP Server Semgrep — local MCP environment

This backend stores Semgrep scan executions over directories, the rule configurations used, and the normalized findings emitted by Semgrep. It also tracks imported/created rules, derived artifacts (analyzed/filtered/exported outputs), and comparisons between two scan runs to support diffing workflows.

Repository: https://github.com/Szowesgad/mcp-server-semgrep
Homepage: https://smithery.ai/server/@Szowesgad/mcp-server-semgrep

## Datastore

- `projects.json` — Represents an MCP-accessible workspace root and logical project boundary for scans, rules, and artifacts. Used to enforce that filesystem paths are within an allowed MCP directory. (12 rows; fields: ['id', 'name', 'mcp_root_path', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(name)
  - constraint: mcp_root_path must be absolute
  - constraint: status in ('active','archived')
- `rules.json` — Catalog of Semgrep rules available to the server, including built-in/indexed rules and custom rules created via create_rule. Stores metadata and on-disk rule file locations. (30 rows; fields: ['id', 'project_id', 'rule_key', 'source', 'language', 'pattern', 'message', 'severity', 'rule_file_path', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'deleted']
  - constraint: unique(project_id, rule_key)
  - constraint: severity in ('ERROR','WARNING','INFO')
  - constraint: if source='custom' then rule_file_path is not null and pattern is not null and message is not null
  - constraint: if rule_file_path is not null then rule_file_path must be absolute
- `scans.json` — A Semgrep scan execution over a directory, including the config used and where raw JSON results were written. Powers scan_directory and serves as the anchor for analysis/filter/export/compare operations. (27 rows; fields: ['id', 'project_id', 'scan_path', 'config', 'results_file_path', 'semgrep_version', 'started_at', 'finished_at', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: scan_path must be absolute
  - constraint: config != ''
  - constraint: if results_file_path is not null then results_file_path must be absolute
  - constraint: finished_at >= started_at when both not null
- `findings.json` — Normalized Semgrep findings extracted from a scan's JSON results. Supports filtering by severity/rule_id/path/language/message, and enables comparisons across scans. (34 rows; fields: ['id', 'scan_id', 'project_id', 'rule_key', 'severity', 'language', 'file_path', 'start_line', 'start_col', 'end_line', 'end_col', 'message', 'fingerprint', 'raw', 'created_at', 'updated_at'])
  - constraint: severity in ('ERROR','WARNING','INFO')
  - constraint: start_line >= 1
  - constraint: start_col is null or start_col >= 1
  - constraint: end_line is null or end_line >= start_line
- `artifacts.json` — Derived outputs produced from raw results: analyzed summaries, filtered subsets, and exported files (text/json/sarif). Also represents stored references to external results_file inputs that were not produced by this service. (41 rows; fields: ['id', 'project_id', 'scan_id', 'source_results_file_path', 'type', 'output_file_path', 'export_format', 'filter_criteria', 'analysis_summary', 'comparison', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['created', 'processing', 'ready', 'failed']
  - constraint: source_results_file_path must be absolute
  - constraint: if output_file_path is not null then output_file_path must be absolute
  - constraint: if type='export' then output_file_path is not null and export_format in ('json','sarif','text')
  - constraint: if type='filtered_results' then filter_criteria is not null

## Business rules enforced by the tools

- scan_directory(path, config): path must resolve under projects.mcp_root_path for the active project; create scans row with status queued->running->(succeeded|failed). On success, scans.results_file_path is set and findings are upserted for that scan (unique by (scan_id, fingerprint)).
- list_rules(language?): returns rules where status='active' and (language matches if provided). The result set must include rule_key, language, severity, and source; custom rules must have rule_file_path.
- create_rule(output_path, pattern, language, message, severity, id): output_path must be absolute and under projects.mcp_root_path; upsert rules by (project_id, rule_key=id) only if existing status != 'deleted'. Persist the rule file to output_path and set rules.source='custom', rules.pattern/message/language/severity, rules.rule_file_path=output_path, rules.status='active'.
- analyze_results(results_file): results_file must be absolute and under projects.mcp_root_path. If it matches an existing scans.results_file_path, analysis may use stored findings; otherwise create an artifacts row type='analysis' with source_results_file_path=results_file and compute/store analysis_summary from parsed JSON.
- filter_results(results_file, severity?, rule_id?, path_pattern?, language?, message_pattern?): create artifacts row type='filtered_results' with filter_criteria capturing all provided filters. Filtering must apply AND semantics across provided criteria. If results_file corresponds to a known scan, filtering should prefer findings table; otherwise parse the file and optionally store an imported_results_reference artifact.
- export_results(results_file, output_file, format): output_file must be absolute and under projects.mcp_root_path. Create artifacts row type='export' with export_format; materialize output_file in selected format from either findings (if known scan) or parsing results_file.
- compare_results(old_results, new_results): both paths must be absolute and under projects.mcp_root_path. Create artifacts row type='comparison' whose comparison object contains input paths and diff statistics. Diff must be computed using a stable fingerprint algorithm consistent with findings.fingerprint when the inputs are known scans.