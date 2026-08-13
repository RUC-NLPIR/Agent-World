# PubMedSearch — local MCP environment

This backend powers a PubMed search and article-detail formatting API. It stores normalized PubMed article metadata (key fields needed for display), plus an audit trail of search requests and the returned PubMed IDs to support caching, repeatability, and usage controls.

Repository: https://github.com/gradusnikov/pubmed-search-mcp-server
Homepage: https://smithery.ai/server/@gradusnikov/pubmed-search-mcp-server

## Datastore

- `api_clients.json` — Represents an API consumer (user/app). Used for rate limiting, attribution, and auditing of searches and fetches. (12 rows; fields: ['id', 'display_name', 'status', 'daily_request_quota', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(display_name)
  - constraint: daily_request_quota >= 0
- `search_requests.json` — Stores each invocation of search_pubmed, including the structured query inputs and the chosen num_results. Supports caching and auditability. (29 rows; fields: ['id', 'client_id', 'title_abstract_keywords', 'authors', 'num_results', 'query_hash', 'status', 'error_message', 'remote_provider', 'remote_request_id', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: num_results between 1 and 200
  - constraint: unique(query_hash)
  - constraint: remote_provider in ('pubmed_eutils')
- `search_results.json` — Stores ordered PubMed IDs returned for a given search request. Enables deterministic replay and subsequent detail-fetching. (33 rows; fields: ['id', 'search_request_id', 'pubmed_id', 'rank', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active']
  - constraint: unique(search_request_id, rank)
  - constraint: unique(search_request_id, pubmed_id)
  - constraint: rank >= 1
  - constraint: pubmed_id length between 1 and 32
- `articles.json` — Canonical cache of PubMed article metadata used by format_paper_details. Populated/updated when details are fetched. (32 rows; fields: ['id', 'pubmed_id', 'title', 'abstract', 'journal', 'publication_year', 'authors', 'doi', 'pmc_id', 'source_url', 'status', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['partial', 'complete', 'stale', 'unavailable']
  - constraint: unique(pubmed_id)
  - constraint: publication_year is null or (publication_year between 1800 and 2100)
  - constraint: pubmed_id length between 1 and 32
- `article_fetches.json` — Audit log of format_paper_details calls and any upstream detail fetches performed for each requested PubMed ID. (31 rows; fields: ['id', 'client_id', 'pubmed_id', 'article_id', 'cache_hit', 'status', 'error_message', 'remote_provider', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: pubmed_id length between 1 and 32
  - constraint: remote_provider in ('pubmed_eutils')
  - constraint: article_id is null or exists(articles.id)

## Business rules enforced by the tools

- search_pubmed(title_abstract_keywords, authors, num_results) must create (or reuse via query_hash) a search_requests row with the exact arrays persisted and num_results persisted; num_results must be enforced to 1..200.
- When a search_requests row transitions to succeeded, the system must insert exactly N search_results rows where N <= search_requests.num_results, with contiguous rank values starting at 1; each (search_request_id, pubmed_id) must be unique.
- format_paper_details(pubmed_ids) must create one article_fetches row per requested pubmed_id, linked to the calling client_id; duplicate pubmed_ids in a single call must be de-duplicated for upstream fetching but still may be logged as separate audit rows only if explicitly configured (default: one row per unique pubmed_id).
- If an articles row exists for a pubmed_id with status in ('complete') and fetched_at is within the freshness window (e.g., 30 days), format_paper_details must serve from cache and set article_fetches.cache_hit=true; otherwise it must refetch and update or create the articles row, setting fetched_at.
- FK integrity must be enforced: search_results.search_request_id must exist; search_requests.client_id and article_fetches.client_id must exist; article_fetches.article_id, when present, must exist.
- Client quota enforcement: for each api_clients row, the total number of tool calls recorded in search_requests plus article_fetches created within a rolling 24h window must be <= daily_request_quota when api_clients.status='active'; if status!='active' all calls must be rejected.