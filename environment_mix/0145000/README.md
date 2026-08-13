# PubChem MCP Server — local MCP environment

This backend powers an MCP server that proxies and caches PubChem compound lookups and searches (by name, SMILES, formula, or CID). It stores normalized compound metadata, executes and logs search requests, and enforces per-api-key quotas/rate limits while persisting returned result sets for fast repeat queries.

Repository: https://github.com/JackKuo666/PubChem-MCP-Server
Homepage: https://smithery.ai/server/@JackKuo666/pubchem-mcp-server

## Datastore

- `api_keys.json` — API keys for clients of the MCP server, including status and quota/rate-limit configuration used to gate PubChem queries. (12 rows; fields: ['id', 'key_hash', 'key_prefix', 'label', 'status', 'daily_request_limit', 'per_minute_limit', 'notes', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix, id)
  - constraint: daily_request_limit >= 0
  - constraint: per_minute_limit >= 0
- `compounds.json` — Normalized cache of PubChem compound records keyed by PubChem CID, storing frequently-used metadata returned by PubChem APIs. (34 rows; fields: ['id', 'pubchem_cid', 'canonical_smiles', 'isomeric_smiles', 'inchi', 'inchi_key', 'molecular_formula', 'molecular_weight', 'iupac_name', 'synonyms', 'pubchem_json', 'cache_status', 'cached_at', 'source_url', 'created_at', 'updated_at'])
  - lifecycle `cache_status`: ['fresh', 'stale', 'error']
  - constraint: unique(pubchem_cid)
  - constraint: pubchem_cid > 0
  - constraint: molecular_weight is null OR molecular_weight > 0
- `search_requests.json` — Log of all tool calls (search by name/smiles/advanced and get by CID), including parameters, execution status, and response metadata. (34 rows; fields: ['id', 'api_key_id', 'tool_name', 'name', 'smiles', 'formula', 'cid', 'max_results', 'status', 'http_status_code', 'error_message', 'request_fingerprint', 'served_from_cache', 'result_count', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: foreign key (api_key_id) references api_keys(id) on delete restrict
  - constraint: max_results between 1 and 100
  - constraint: cid is null OR cid > 0
  - constraint: result_count >= 0
- `search_results.json` — Materialized results for a search request, linking requests to returned compounds in ranked order (supports max_results behavior). (32 rows; fields: ['id', 'search_request_id', 'compound_id', 'rank', 'match_type', 'score', 'created_at', 'updated_at'])
  - lifecycle `match_type`: ['name', 'smiles', 'formula', 'cid', 'mixed']
  - constraint: foreign key (search_request_id) references search_requests(id) on delete cascade
  - constraint: foreign key (compound_id) references compounds(id) on delete restrict
  - constraint: unique(search_request_id, rank)
  - constraint: unique(search_request_id, compound_id)
- `usage_counters.json` — Aggregated per-api-key counters for quota enforcement and analytics (daily and rolling-minute windows). (29 rows; fields: ['id', 'api_key_id', 'window_type', 'window_start', 'request_count', 'succeeded_count', 'failed_count', 'created_at', 'updated_at'])
  - lifecycle `window_type`: ['day', 'minute']
  - constraint: foreign key (api_key_id) references api_keys(id) on delete cascade
  - constraint: unique(api_key_id, window_type, window_start)
  - constraint: request_count >= 0
  - constraint: succeeded_count >= 0

## Business rules enforced by the tools

- For every tool invocation, a search_requests row MUST be created with tool_name matching the invoked tool and parameters mapped to the corresponding nullable columns (name/smiles/formula/cid/max_results).
- max_results MUST default to 5 when omitted and MUST be clamped/rejected to the range [1, 100].
- get_pubchem_compound_by_cid MUST set cid and MUST ignore/reject name/smiles/formula if provided; cid MUST be > 0.
- search_pubchem_by_name MUST require name to be non-empty after trimming; search_pubchem_by_smiles MUST require smiles to be non-empty after trimming.
- search_pubchem_advanced MUST require at least one of (name, smiles, formula, cid) to be non-null; otherwise the request MUST fail validation.
- API key status MUST be 'active' to execute tools; 'suspended' and 'revoked' keys MUST be rejected before creating external PubChem traffic (but the attempt MAY still be logged as failed).
- Per-api-key rate limits MUST be enforced using usage_counters: within the current minute window, request_count MUST NOT exceed api_keys.per_minute_limit; within the current UTC day window, request_count MUST NOT exceed api_keys.daily_request_limit.
- On request execution, search_requests transitions MUST follow: queued -> running -> (succeeded|failed). Direct queued->succeeded is not allowed.
- If served_from_cache is true for a search request, no outbound PubChem request may be made and http_status_code SHOULD be null or represent cached origin metadata.
- For search tools, the backend MUST persist ranked results in search_results with rank starting at 1 and contiguous up to result_count; number of rows in search_results for a request MUST equal search_requests.result_count.
- compounds MUST be unique by pubchem_cid; inserting a compound for an existing pubchem_cid MUST upsert and update cached_at/updated_at.
- If PubChem fetch fails for a compound refresh, compounds.cache_status MUST transition to 'error' and the error MUST be recorded on the owning search_requests row (status=failed, error_message populated).