# CiteAssist MCP — local MCP environment

CiteAssist MCP stores citation lookup requests (by resource identifier or Scholar query), the resolved normalized publication records, and provider-specific retrieval attempts that return BibTeX. Main workflows: accept a lookup request, fetch from an upstream provider (CiteAs or Google Scholar), store attempts/results, and serve cached BibTeX for repeat requests subject to quotas and integrity constraints.

Repository: https://github.com/ndchikin/reference-mcp
Homepage: https://smithery.ai/server/@ndchikin/reference-mcp

## Datastore

- `api_clients.json` — Represents calling clients (e.g., MCP server instance/tenant) and their quota/limits for upstream citation retrieval. (12 rows; fields: ['id', 'name', 'status', 'daily_request_limit', 'monthly_request_limit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: daily_request_limit >= 0
  - constraint: monthly_request_limit >= 0
- `citation_requests.json` — Top-level user requests to retrieve BibTeX citations either by a direct resource (CiteAs) or a search query (Google Scholar). (18 rows; fields: ['id', 'client_id', 'provider', 'resource', 'query', 'results_requested', 'status', 'cache_key', 'cache_hit', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(client_id) references api_clients.id
  - constraint: unique(client_id, cache_key)
  - constraint: provider in ('citeas','scholar')
  - constraint: ((provider='citeas' and resource is not null and query is null and results_requested is null) or (provider='scholar' and query is not null))
- `provider_attempts.json` — Individual upstream fetch attempts for a citation request, including raw response payload and parsing outcome. (18 rows; fields: ['id', 'request_id', 'attempt_no', 'provider', 'status', 'http_status', 'latency_ms', 'raw_response', 'parse_status', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['started', 'succeeded', 'failed']
  - constraint: fk(request_id) references citation_requests.id
  - constraint: unique(request_id, attempt_no)
  - constraint: attempt_no >= 1 and attempt_no <= 10
  - constraint: http_status is null or (http_status >= 100 and http_status <= 599)
- `publications.json` — Normalized publication entities resolved from upstream results; used to de-duplicate across requests and providers. (18 rows; fields: ['id', 'canonical_title', 'doi', 'url', 'year', 'authors', 'source_provider', 'status', 'merged_into_publication_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'merged', 'deleted']
  - constraint: unique(doi) where doi is not null
  - constraint: year is null or (year >= 1400 and year <= 2200)
  - constraint: status != 'merged' or merged_into_publication_id is not null
  - constraint: merged_into_publication_id is null or fk(merged_into_publication_id) references publications.id
- `citations.json` — Provider-specific BibTeX outputs linked to a request and optionally to a normalized publication; supports multiple results for Scholar queries. (19 rows; fields: ['id', 'request_id', 'attempt_id', 'publication_id', 'provider', 'result_rank', 'bibtex', 'bibtex_key', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded', 'deleted']
  - constraint: fk(request_id) references citation_requests.id
  - constraint: attempt_id is null or fk(attempt_id) references provider_attempts.id
  - constraint: publication_id is null or fk(publication_id) references publications.id
  - constraint: unique(request_id, result_rank)

## Business rules enforced by the tools

- Tool get_citeas_data(resource): creates or reuses a citation_requests row with provider='citeas', resource set, query/results_requested null, and results_requested must be null; on success it must produce exactly one citations row with result_rank=1 and provider='citeas'.
- Tool get_scholar_data(query, results): creates or reuses a citation_requests row with provider='scholar' and query set; if results is omitted it is treated as 2; it must produce between 1 and results_requested citations rows with provider='scholar' and contiguous result_rank starting at 1.
- Requests are cacheable by (client_id, cache_key); if a matching succeeded request exists and its citations are present, a new call returns cached citations and sets citation_requests.cache_hit=true without creating a new provider_attempts row.
- A citation_requests row may transition from queued->running only once; once in succeeded/failed/cancelled it is terminal and must not change status (except updated_at).
- Quota enforcement: for a given api_clients row with status='active', the system must reject starting a new provider_attempts row if the client's successful attempts today would exceed daily_request_limit or this month would exceed monthly_request_limit; cached responses do not count against these limits.
- For provider_attempts, attempt_no increments per request and must not exceed 10; creating a new attempt requires the parent citation_requests.status to be queued or running, and will set it to running if it was queued.
- When a publication is merged (status='merged'), all active citations referencing the merged publication_id must be updated to point to merged_into_publication_id (or marked superseded) in a single transaction to maintain referential integrity.
- For publications, doi (when present) is globally unique after normalization; attempts to insert a duplicate DOI must instead link citations to the existing publications row.