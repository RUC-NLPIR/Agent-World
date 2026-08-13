# Shodan Server — local MCP environment

This backend stores authenticated client access, request logs, and cached Shodan-derived intelligence objects (hosts, DNS resolutions, and vulnerability/CVE/CPE data) to serve lookup/search tools with rate limits and auditability. The main workflows are: authenticate via API key, execute a tool request, optionally hydrate/update cached entities from upstream Shodan, and record usage for quota enforcement and analytics.

Repository: https://github.com/BurtTheCoder/mcp-shodan
Homepage: https://smithery.ai/server/@burtthecoder/mcp-shodan

## Datastore

- `api_keys.json` — API keys that authenticate callers of the Shodan Server. Used for access control, per-key quotas, and usage tracking. (18 rows; fields: ['id', 'key_hash', 'key_prefix', 'label', 'owner', 'status', 'plan', 'requests_per_minute', 'requests_per_day', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix, owner)
  - constraint: requests_per_minute >= 1
  - constraint: requests_per_day >= 1
- `tool_requests.json` — Immutable log of each tool invocation (input, output metadata, status, latency, errors). Supports auditing, debugging, and quota enforcement across all 7 tools. (19 rows; fields: ['id', 'api_key_id', 'tool_name', 'status', 'request_params', 'normalized_query', 'result_summary', 'error_code', 'error_message', 'upstream_provider', 'upstream_request_id', 'cache_hit', 'latency_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'rate_limited']
  - constraint: latency_ms is null or latency_ms >= 0
  - constraint: cache_hit in (true,false)
  - constraint: error_message is null or length(error_message) <= 4000
  - constraint: tool_name in ('ip_lookup','shodan_search','cve_lookup','dns_lookup','cpe_lookup','cves_by_product','reverse_dns_lookup')
- `hosts.json` — Cached host intelligence for IP addresses as returned by Shodan (services/ports, org/ISP, geo, tags, and vulnerability identifiers). Used primarily by ip_lookup and also as a materialized cache for shodan_search results. (20 rows; fields: ['id', 'ip', 'ip_version', 'status', 'last_fetched_at', 'expires_at', 'raw_host', 'open_ports', 'hostnames', 'country_code', 'asn', 'org', 'isp', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'refreshing', 'error']
  - constraint: unique(ip)
  - constraint: ip_version in ('ipv4','ipv6')
  - constraint: country_code is null or length(country_code) = 2
- `search_queries.json` — Stored Shodan search executions and their result metadata, including country statistics and cached host hits. Powers shodan_search and allows replay/analytics. (19 rows; fields: ['id', 'tool_request_id', 'api_key_id', 'query', 'status', 'total_matches', 'country_stats', 'result_host_ips', 'raw_search_response', 'created_at', 'updated_at'])
  - lifecycle `status`: ['running', 'succeeded', 'failed']
  - constraint: total_matches is null or total_matches >= 0
  - constraint: unique(tool_request_id)
  - constraint: length(query) >= 1
- `dns_records.json` — Cached DNS forward and reverse lookups. Supports batch dns_lookup (hostname->IPs) and reverse_dns_lookup (ip->hostnames), with TTL-based staleness. (17 rows; fields: ['id', 'record_type', 'query_name', 'status', 'answers', 'ttl_seconds', 'last_fetched_at', 'expires_at', 'raw_dns_response', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'refreshing', 'nxdomain', 'error']
  - constraint: unique(record_type, query_name)
  - constraint: ttl_seconds is null or ttl_seconds >= 0
  - constraint: length(query_name) >= 1
- `vuln_intel.json` — Unified vulnerability intelligence cache for CVEs and CPEs from Shodan CVEDB. Supports cve_lookup (by CVE), cpe_lookup (search by product name), and cves_by_product (CPE/product -> CVEs with filters). (19 rows; fields: ['id', 'entity_type', 'cve_id', 'cpe23', 'vendor', 'product', 'version', 'status', 'cvss_v2_score', 'cvss_v3_score', 'epss_probability', 'epss_percentile', 'kev', 'ransomware_campaign', 'published_at', 'modified_at', 'last_fetched_at', 'expires_at', 'raw', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'refreshing', 'error']
  - constraint: unique(cve_id) where entity_type='cve'
  - constraint: unique(cpe23) where entity_type='cpe'
  - constraint: cvss_v2_score is null or (cvss_v2_score >= 0 and cvss_v2_score <= 10)
  - constraint: cvss_v3_score is null or (cvss_v3_score >= 0 and cvss_v3_score <= 10)

## Business rules enforced by the tools

- All 7 tools must create exactly one tool_requests row per invocation; tool_requests.request_params must store the raw JSON input (may be {}).
- A request must be rejected (and logged with tool_requests.status='rate_limited') if the calling api_key is not 'active' or exceeds requests_per_minute rolling window or requests_per_day for the current UTC day.
- tool_requests.status must follow the declared lifecycle transitions and must be terminal once in 'succeeded', 'failed', or 'rate_limited'.
- ip_lookup must resolve to a hosts row by canonicalized IP string; if hosts.status is 'fresh' and expires_at > now(), return from cache with cache_hit=true; otherwise refresh from upstream and update hosts.raw_host, last_fetched_at, expires_at, and status.
- shodan_search must persist a search_queries row linked to tool_requests.id; search_queries.query must be non-empty and may be derived from request_params if present; the server must store any country-based statistics in search_queries.country_stats when available.
- dns_lookup and reverse_dns_lookup must read/write dns_records by (record_type, query_name); for forward lookups record_type must be 'A' and/or 'AAAA' and query_name must be a hostname; for reverse lookups record_type must be 'PTR' and query_name must be a canonical IP string.
- dns_records.status='nxdomain' must only be used when upstream indicates no such domain/record; it must not be returned for transport/auth errors (use 'error').
- cve_lookup must upsert a vuln_intel row with entity_type='cve' and matching cve_id; it must validate cve_id format 'CVE-YYYY-NNNN...' before calling upstream.
- cpe_lookup must query vuln_intel where entity_type='cpe' and product/vendor match the searched product name when cache is sufficient; if cache is stale/empty it must fetch from upstream and upsert by cpe23.
- cves_by_product must support querying by product name and/or cpe23; filtering by KEV must be implemented using vuln_intel.kev; sorting by EPSS must use vuln_intel.epss_probability; date range filters must apply to vuln_intel.published_at when present.
- All cached entities (hosts, dns_records, vuln_intel) must include TTL-based staleness via expires_at; refresh operations must set status='refreshing' while in-flight and then 'fresh' or 'error' on completion.