# VirusTotal MCP Server — local MCP environment

This backend stores VirusTotal-oriented lookups and cached analysis artifacts for observables (files, URLs, domains, IPs), plus relationship edges and VT Intelligence search executions. The main workflows are: (1) a client requests a report for an observable which triggers/reads a cached report and its key relationship summaries, (2) the client pages through a specific relationship type for an observable, and (3) the client runs an advanced VT Intelligence corpus search and pages results while tracking quota and access level.

Repository: https://github.com/emeryray2002/virustotal-mcp
Homepage: https://smithery.ai/server/@emeryray2002/virustotal-mcp

## Datastore

- `api_clients.json` — Represents calling tenants/clients and their VirusTotal API credentials and entitlements (e.g., Intelligence access). Used to authorize tools, enforce quota, and attribute cached data to the client that fetched it. (17 rows; fields: ['id', 'name', 'api_key_hash', 'key_tier', 'intelligence_enabled', 'daily_quota_requests', 'daily_quota_relationship_pages', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(name)
  - constraint: unique(api_key_hash)
  - constraint: daily_quota_requests >= 0
  - constraint: daily_quota_relationship_pages >= 0
- `observables.json` — Normalized observables queried against VirusTotal: file hashes, URLs, domains, and IP addresses. Reports and relationship edges attach to an observable record. (18 rows; fields: ['id', 'type', 'value', 'file_hash_kind', 'url_normalization_version', 'first_seen_at', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `type`: ['file', 'url', 'domain', 'ip']
  - constraint: unique(type, value)
  - constraint: if type = 'file' then file_hash_kind is not null
  - constraint: if type != 'file' then file_hash_kind is null
  - constraint: if type = 'url' then url_normalization_version is not null
- `reports.json` — Cached VirusTotal reports for an observable, including summary fields and pre-fetched key relationship summaries used by get_*_report tools and file behavior summary. (20 rows; fields: ['id', 'client_id', 'observable_id', 'report_kind', 'vt_object_id', 'status', 'source_updated_at', 'expires_at', 'summary', 'relationship_summaries', 'raw_vt_payload', 'last_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'fetching', 'error']
  - constraint: unique(client_id, observable_id, report_kind)
  - constraint: expires_at is null or expires_at >= created_at
- `relationships.json` — Edges between an observable and related entities returned by VT relationship endpoints (paged). Supports get_*_relationship tools with relationship_type and pagination cursoring. (18 rows; fields: ['id', 'client_id', 'from_observable_id', 'relationship_type', 'to_observable_id', 'to_external_type', 'to_external_id', 'to_display', 'vt_cursor', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `to_external_type`: ['observable', 'certificate', 'whois', 'threat_actor', 'asn', 'unknown']
  - constraint: if to_observable_id is not null then to_external_type = 'observable'
  - constraint: if to_observable_id is null then to_external_id is not null
  - constraint: unique(client_id, from_observable_id, relationship_type, coalesce(to_observable_id, ''), coalesce(to_external_id, ''))
- `search_jobs.json` — Represents VT Intelligence advanced corpus searches and their paginated result retrieval. Used by advanced_corpus_search tool to cache results, track cursors, and enforce entitlement/quota. (19 rows; fields: ['id', 'client_id', 'query', 'status', 'page_size', 'next_cursor', 'result_items', 'total_estimated', 'last_fetched_at', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['running', 'completed', 'error', 'cancelled']
  - constraint: page_size >= 1
  - constraint: page_size <= 200
  - constraint: if status = 'error' then error_message is not null

## Business rules enforced by the tools

- All tools execute in the context of exactly one api_clients row; requests are rejected if api_clients.status != 'active'.
- advanced_corpus_search is allowed only when api_clients.intelligence_enabled = true; otherwise return an authorization error.
- For get_file_report/get_url_report/get_domain_report/get_ip_report/get_file_behavior_summary: the service must upsert an observables row (unique(type,value)), then upsert a reports row (unique(client_id,observable_id,report_kind)).
- When serving a report tool, if reports.status in ('stale','error') or reports.expires_at <= now() or reports.last_fetched_at is null, the service transitions the report to 'fetching', performs the upstream VT call(s), stores summary/relationship_summaries/raw_vt_payload, sets last_fetched_at, sets status='fresh', and updates expires_at according to cache policy.
- Relationship tools (get_file_relationship/get_url_relationship/get_domain_relationship/get_ip_relationship) must validate that relationship_type is compatible with the observable type; incompatible requests are rejected before calling upstream VT.
- Relationship tools must enforce pagination by persisting vt_cursor on relationships rows and must not fetch more pages than api_clients.daily_quota_relationship_pages per UTC day.
- For each upstream VT request (report fetch, relationship page, search page), increment a per-client daily request counter (implemented outside this model or as a computed view); deny when it would exceed api_clients.daily_quota_requests.
- relationships rows may reference either to_observable_id (for related files/urls/domains/ips) or (to_external_type,to_external_id) for non-observable VT entities; both forms cannot be null.
- Search jobs are owned by a single client; only that client may continue pagination using next_cursor. When next_cursor becomes null, status transitions to 'completed'.
- All foreign keys must enforce integrity: reports.client_id, relationships.client_id, search_jobs.client_id reference api_clients.id; reports.observable_id and relationships.from_observable_id reference observables.id; relationships.to_observable_id references observables.id when present.