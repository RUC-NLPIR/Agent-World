# Whodis Domain Availability Server — local MCP environment

This backend stores requests to check domain name availability via WHOIS lookups, along with per-domain results and the WHOIS/TLD resolver configuration used to perform checks. The main workflow is: accept a batch availability check request, enqueue/execute WHOIS queries per domain, store normalized results (available/unavailable/unknown) and return the split lists.

Repository: https://github.com/vinsidious/whodis-mcp-server
Homepage: https://smithery.ai/server/@vinsidious/whodis-mcp-server

## Datastore

- `availability_checks.json` — A single API call to check availability for one or more domains. Stores request metadata, lifecycle state, and aggregated outcome counters. (18 rows; fields: ['id', 'request_id', 'input_domains', 'deduped_domain_count', 'status', 'available_count', 'unavailable_count', 'unknown_count', 'error_message', 'started_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'completed', 'failed', 'cancelled']
  - constraint: unique(request_id)
  - constraint: deduped_domain_count >= 0
  - constraint: available_count >= 0
  - constraint: unavailable_count >= 0
- `domain_checks.json` — One row per domain within an availability check batch. Stores normalized domain, TLD, result classification, and diagnostic details. (18 rows; fields: ['id', 'availability_check_id', 'input_domain', 'normalized_domain', 'tld', 'status', 'classification', 'whois_server_id', 'whois_query', 'whois_response_raw', 'matched_pattern', 'response_latency_ms', 'error_code', 'error_message', 'attempts', 'next_retry_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'querying_whois', 'classified', 'error']
  - constraint: foreign key(availability_check_id) references availability_checks(id) on delete cascade
  - constraint: unique(availability_check_id, normalized_domain)
  - constraint: length(normalized_domain) between 1 and 253
  - constraint: attempts >= 0
- `whois_servers.json` — Catalog of WHOIS servers by TLD/suffix with query settings, throttling configuration, and health state used by the checker. (18 rows; fields: ['id', 'tld', 'host', 'port', 'query_template', 'timeout_ms', 'max_requests_per_minute', 'status', 'last_healthcheck_at', 'last_error_at', 'notes', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'degraded', 'disabled']
  - constraint: unique(tld)
  - constraint: port between 1 and 65535
  - constraint: timeout_ms between 100 and 60000
  - constraint: max_requests_per_minute between 1 and 10000
- `whois_classification_rules.json` — Rules used to interpret WHOIS responses for a TLD/WHOIS server and classify a domain as available/unavailable/unknown. (17 rows; fields: ['id', 'whois_server_id', 'match_type', 'match_value', 'classifies_as', 'priority', 'enabled', 'created_at', 'updated_at'])
  - lifecycle `enabled`: ['true', 'false']
  - constraint: foreign key(whois_server_id) references whois_servers(id) on delete cascade
  - constraint: priority >= 0
  - constraint: unique(whois_server_id, priority)
  - constraint: classifies_as in ('available','unavailable')

## Business rules enforced by the tools

- Tool `check-domain-availability` must create an availability_checks row and one domain_checks row per unique normalized domain derived from the input `domains` array.
- The `domains` tool parameter maps to availability_checks.input_domains and domain_checks.input_domain/normalized_domain; the tool response arrays are derived from domain_checks.classification for the batch (available => 'available', unavailable => 'unavailable', unknown is omitted from both arrays unless the API explicitly chooses to return it).
- Normalization must lowercase, trim surrounding whitespace, remove any trailing dot, and convert IDN to punycode; domain_checks.normalized_domain must be used for uniqueness within a batch.
- A domain_checks row must only be classified as 'available' or 'unavailable' if a WHOIS response was successfully retrieved and at least one enabled whois_classification_rules rule matched; otherwise classification must be 'unknown' and error_code/error_message populated when applicable.
- If whois_servers.status='disabled', it must not be selected for new domain_checks; if all candidate servers are disabled or missing for a TLD, domain_checks must be set to classification='unknown' with error_code='unsupported_tld'.
- Batch counters on availability_checks (available_count/unavailable_count/unknown_count) must equal the counts of domain_checks by classification for that batch when the batch is in a terminal state (completed/failed/cancelled).
- Enforce reasonable limits: availability_checks.input_domains must have minItems=1 and a maximum of 1000 items; any request exceeding this must be rejected before persisting domain_checks rows.
- whois_response_raw must be stored with a maximum size (e.g. 64KB); if larger, it must be truncated and a note included in domain_checks.error_message or matched_pattern as appropriate.