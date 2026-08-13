# NIF Portugal MCP Server — local MCP environment

This backend stores a searchable registry of Portuguese companies keyed by NIF, along with location/name indexes to support lookup by name and city. It also tracks API clients and request logs to enforce quotas and provide operational auditability for the MCP tools.

Repository: https://github.com/ruicarvalho1/MCP_Nif
Homepage: https://smithery.ai/server/@ruicarvalho1/mcp_nif

## Datastore

- `api_clients.json` — Registered MCP/API consumers used for authentication, rate limiting, and quota enforcement. (12 rows; fields: ['id', 'name', 'status', 'api_key_hash', 'quota_requests_per_day', 'quota_requests_per_minute', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: unique(api_key_hash)
  - constraint: quota_requests_per_day >= 0
  - constraint: quota_requests_per_minute >= 0
- `companies.json` — Canonical company registry records keyed by Portuguese NIF, including status flags used by the MCP tools. (18 rows; fields: ['id', 'nif', 'legal_name', 'normalized_name', 'city', 'address', 'postal_code', 'company_type', 'is_accounting_company', 'active_status', 'record_status', 'source', 'last_verified_at', 'created_at', 'updated_at'])
  - lifecycle `record_status`: ['current', 'deprecated', 'deleted']
  - constraint: unique(nif)
  - constraint: length(nif) = 9
  - constraint: nif matches regex '^[0-9]{9}$'
  - constraint: active_status in ('active','inactive','unknown')
- `company_aliases.json` — Alternate/previous names for companies to improve name-based matching and NIF discovery. (18 rows; fields: ['id', 'company_id', 'alias_name', 'normalized_alias_name', 'alias_type', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: foreign key(company_id) references companies(id) on delete cascade
  - constraint: unique(company_id, normalized_alias_name)
  - constraint: normalized_alias_name != ''
- `search_requests.json` — Audit log of tool invocations and their outcomes, used for monitoring and quota enforcement. (18 rows; fields: ['id', 'client_id', 'tool_name', 'input_nif', 'input_name', 'input_city', 'matched_company_id', 'result_count', 'status', 'latency_ms', 'error_code', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ok', 'not_found', 'invalid_input', 'rate_limited', 'error']
  - constraint: foreign key(client_id) references api_clients(id)
  - constraint: latency_ms is null or latency_ms >= 0
  - constraint: result_count >= 0
  - constraint: input_nif is null or (length(input_nif)=9 and input_nif matches regex '^[0-9]{9}$')

## Business rules enforced by the tools

- All tools that accept nif must validate it matches regex '^[0-9]{9}$'; otherwise record a search_requests row with status=invalid_input and return an input error.
- get_company(nif) reads companies by companies.nif where record_status != 'deleted'; if none found, return not found and log status=not_found.
- is_accounting_company(nif) returns companies.is_accounting_company for the matched company; if not found, return false (or not found depending on API behavior) and log accordingly.
- is_active(nif) returns true only when the matched company has active_status='active' and record_status='current'; if active_status='unknown' the tool must return false (conservative) and log ok with matched_company_id.
- search_companies_by_name_and_city(name, city) performs case/diacritic-insensitive matching against companies.normalized_name and companies.city (or normalized city in implementation) and returns a list of companies; matches must exclude record_status='deleted'.
- find_nif_by_name(name) searches companies.normalized_name plus company_aliases.normalized_alias_name (active aliases only) and returns one or more candidate NIFs ordered by best match; deleted companies must be excluded.
- For every tool invocation, a search_requests row must be written with tool_name and the provided parameters (input_nif/input_name/input_city) and a non-null result_count.
- Requests must be rejected (status=rate_limited) when a client exceeds api_clients.quota_requests_per_minute or api_clients.quota_requests_per_day; rate-limited requests must still be logged in search_requests.
- api_clients with status != 'active' cannot execute tools; attempts must be logged with status=rate_limited or error (implementation choice) and must not return company data.
- Uniqueness must be enforced on companies.nif and on company_aliases(company_id, normalized_alias_name) to prevent duplicate index entries that would skew search results.