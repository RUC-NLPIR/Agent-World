# LLMS.txt Explorer — local MCP environment

This backend tracks websites that have been checked for the presence of llms.txt and llms-full.txt, along with the discovered file locations and the results of each check. The main workflows are: (1) run a check for a given URL, store a normalized website record and the check attempt, then store any discovered llms*.txt artifacts; (2) list known websites with optional filters based on discovered artifacts.

Repository: https://github.com/thedaviddias/mcp-llms-txt-explorer
Homepage: https://smithery.ai/server/@thedaviddias/mcp-llms-txt-explorer

## Datastore

- `websites.json` — Canonical, normalized representation of a website (origin + host) that can be checked for llms.txt artifacts and listed in the directory. (18 rows; fields: ['id', 'input_url', 'canonical_origin', 'scheme', 'host', 'port', 'last_checked_at', 'has_llms_txt', 'has_llms_full_txt', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(canonical_origin)
  - constraint: scheme in ('http','https')
  - constraint: port is null or (port >= 1 and port <= 65535)
  - constraint: canonical_origin != '' and host != ''
- `website_checks.json` — Each invocation/attempt to check a website for llms.txt-related files, including outcomes and network metadata. (18 rows; fields: ['id', 'website_id', 'requested_url', 'resolved_origin', 'status', 'http_status_code', 'error_code', 'error_message', 'attempted_paths', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: fk(website_id) references websites(id) on delete cascade
  - constraint: http_status_code is null or (http_status_code >= 100 and http_status_code <= 599)
  - constraint: started_at is null or created_at <= started_at
  - constraint: finished_at is null or (started_at is not null and started_at <= finished_at)
- `llms_artifacts.json` — Discovered llms.txt and llms-full.txt files for a website, including where they were found and fetch metadata. (19 rows; fields: ['id', 'website_id', 'first_discovered_check_id', 'last_verified_check_id', 'type', 'url', 'path', 'http_status_code', 'content_type', 'etag', 'last_modified', 'status', 'first_discovered_at', 'last_verified_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'gone', 'invalid']
  - constraint: fk(website_id) references websites(id) on delete cascade
  - constraint: fk(first_discovered_check_id) references website_checks(id) on delete set null
  - constraint: fk(last_verified_check_id) references website_checks(id) on delete set null
  - constraint: unique(website_id, type, url)
- `api_request_logs.json` — Operational audit log of tool calls, used for rate-limiting, abuse detection, and basic analytics. (18 rows; fields: ['id', 'tool_name', 'input', 'website_id', 'request_ip', 'user_agent', 'status', 'error_message', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ok', 'error']
  - constraint: tool_name in ('check_website','list_websites')
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: status = 'error' implies error_message is not null
  - constraint: fk(website_id) references websites(id) on delete set null

## Business rules enforced by the tools

- check_website(url) must normalize the input into (scheme, host, port, canonical_origin); it must upsert websites by unique(canonical_origin) and update websites.input_url and websites.updated_at.
- check_website(url) must create a website_checks row for the target website with attempted_paths including '/llms.txt' and '/llms-full.txt'; status must transition queued -> running -> (succeeded|failed).
- On a succeeded check_website, discovered artifacts must be upserted into llms_artifacts by unique(website_id,type,url); first_discovered_at and first_discovered_check_id are set only on initial insert; last_verified_at and last_verified_check_id must be updated on each verification.
- websites.has_llms_txt must be true iff there exists at least one llms_artifacts row with website_id=websites.id, type='llms.txt', status='active'. Likewise for websites.has_llms_full_txt and type='llms-full.txt'. These booleans must be updated transactionally with artifact writes.
- If a check_website attempt determines a previously active artifact is no longer retrievable (e.g. 404/410), the corresponding llms_artifacts.status must transition from active -> gone and websites.has_* flags must be recomputed accordingly.
- list_websites(filter_llms_txt, filter_llms_full_txt) must return websites where status='active', optionally filtered by websites.has_llms_txt=true when filter_llms_txt=true and by websites.has_llms_full_txt=true when filter_llms_full_txt=true; if both filters are true, both conditions must hold.
- Invalid URLs (parse failure, unsupported scheme) must not create a websites row; they must create an api_request_logs row with tool_name='check_website', status='error'.
- All foreign keys must be enforced: no llms_artifacts or website_checks may exist without a corresponding websites row.
- Rate limiting/abuse controls (if enabled) must be computed from api_request_logs aggregated by request_ip over a rolling window; requests exceeding configured thresholds must be rejected and logged with status='error'.