# Perplexity Search — local MCP environment

This backend stores authenticated web search requests executed via the Perplexity Search MCP server, along with the normalized results returned from the upstream provider. The primary workflow is: an API key (or anonymous session) issues a search call, a query record is created, results are stored, and usage is aggregated for quotas/billing and audit.

Repository: https://github.com/arjunkmrm/perplexity-search
Homepage: https://smithery.ai/server/@arjunkmrm/perplexity-search

## Datastore

- `workspaces.json` — Tenant container for API consumers. Holds plan/quota settings and is the parent for API keys and search queries. (12 rows; fields: ['id', 'name', 'status', 'plan', 'monthly_search_quota', 'monthly_result_quota', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: monthly_search_quota >= -1
  - constraint: monthly_result_quota >= -1
- `api_keys.json` — API keys used to authenticate callers (the MCP server or end-users) and attribute usage to a workspace. (12 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'prefix', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: unique(workspace_id, name)
  - constraint: unique(prefix)
  - constraint: key_hash length >= 32
- `search_queries.json` — A single invocation of the search tool. Stores request/response metadata, status, and links to result rows. (18 rows; fields: ['id', 'workspace_id', 'api_key_id', 'status', 'request_payload', 'normalized_query_text', 'provider', 'provider_request_id', 'response_payload', 'http_status', 'error_code', 'error_message', 'started_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: fk(api_key_id) references api_keys(id) on delete set null
  - constraint: http_status between 100 and 599 or http_status is null
  - constraint: request_payload is valid json object
- `search_results.json` — Individual results/citations returned for a given search query. Supports storing multiple result rows per query. (18 rows; fields: ['id', 'query_id', 'rank', 'title', 'url', 'snippet', 'source', 'published_at', 'score', 'raw', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'redacted']
  - constraint: fk(query_id) references search_queries(id) on delete cascade
  - constraint: unique(query_id, rank)
  - constraint: rank >= 1
  - constraint: score is null or score >= 0
- `usage_events.json` — Append-only usage ledger for quota/billing and auditing. One row per tool invocation and optional per-result accounting. (16 rows; fields: ['id', 'workspace_id', 'api_key_id', 'query_id', 'event_type', 'quantity', 'cost_usd', 'occurred_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['posted', 'voided']
  - constraint: fk(workspace_id) references workspaces(id) on delete restrict
  - constraint: fk(api_key_id) references api_keys(id) on delete set null
  - constraint: fk(query_id) references search_queries(id) on delete cascade
  - constraint: quantity >= 0

## Business rules enforced by the tools

- The search tool MUST create a search_queries row with request_payload = {} when no parameters are supplied, and set provider = 'perplexity'.
- A search_queries row MUST transition status from queued -> running -> (succeeded|failed|cancelled); any other transition is rejected.
- When a search succeeds, the service MUST insert >= 0 search_results rows linked by query_id, with contiguous unique ranks starting at 1 for the stored subset.
- For each search_queries row that reaches status succeeded|failed|cancelled, completed_at MUST be set and must be >= started_at.
- If an api_key is provided, it MUST be active; revoked keys cannot create new search_queries rows.
- Workspaces in status suspended or deleted cannot create new search_queries rows.
- On each successful search invocation, exactly one usage_events row with event_type='search_invocation' and quantity=1 MUST be posted for the query_id.
- If results are persisted, exactly one usage_events row with event_type='results_stored' and quantity = count(search_results where query_id=...) MUST be posted for the query_id.
- Monthly quota enforcement: for a workspace with monthly_search_quota != -1, the count of posted usage_events(event_type='search_invocation') in the current calendar month MUST be <= monthly_search_quota at commit time; otherwise the search is rejected.
- Monthly quota enforcement: for a workspace with monthly_result_quota != -1, the sum of posted usage_events(event_type='results_stored').quantity in the current calendar month MUST be <= monthly_result_quota at commit time; otherwise result persistence is truncated or the search is rejected per server policy.
- FK integrity: deleting a workspace is a soft-delete via status='deleted'; physical deletes are disallowed while dependent rows exist.