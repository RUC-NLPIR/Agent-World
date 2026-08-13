# PubMed Server — local MCP environment

This backend powers a PubMed-facing search API that logs and rate-limits client calls, caches PubMed article metadata/abstract/full-text when available, and materializes citation/similarity relationships to speed repeated lookups. Main workflows are: clients execute searches (basic/author/journal/advanced/batch), the service fetches from upstream (NCBI E-utilities / PMC) as needed, stores normalized article records, and returns results while recording per-request usage and enforcing quotas.

Repository: https://github.com/t0mst0ne/pubmed-mcp-easy
Homepage: https://smithery.ai/server/@t0mst0ne/pubmed-mcp-easy

## Datastore

- `api_clients.json` — Represents an API consumer (workspace/app) and its auth + quota configuration used to enforce limits across all PubMed tools. (26 rows; fields: ['id', 'name', 'status', 'api_key_hash', 'api_key_last4', 'requests_per_minute', 'requests_per_day', 'cache_ttl_seconds', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: unique(api_key_hash)
  - constraint: requests_per_minute BETWEEN 1 AND 6000
  - constraint: requests_per_day BETWEEN 1 AND 500000
- `request_logs.json` — Immutable log of every tool call for auditing, debugging, caching decisions, and quota enforcement across pubmed_search/similar/cites/cited_by/abstract/open_access/full_text/batch/author/advanced/journal. (34 rows; fields: ['id', 'client_id', 'tool_name', 'status', 'input', 'normalized_query', 'target_pmid', 'batch_parent_request_id', 'response_cache_key', 'cache_hit', 'http_status', 'error_code', 'error_message', 'upstream_provider', 'upstream_latency_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed', 'rate_limited']
  - constraint: foreign key (client_id) references api_clients(id)
  - constraint: foreign key (target_pmid) references articles(pmid)
  - constraint: foreign key (batch_parent_request_id) references request_logs(id)
  - constraint: http_status BETWEEN 100 AND 599 OR http_status IS NULL
- `articles.json` — Canonical cached PubMed article metadata and content pointers used to answer abstract/open_access/full_text and enrich search/citation/similar results. (34 rows; fields: ['pmid', 'pmc_id', 'doi', 'title', 'journal', 'publication_date', 'authors', 'mesh_terms', 'abstract_text', 'open_access', 'full_text_source', 'full_text', 'record_status', 'last_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `record_status`: ['stub', 'metadata_fetched', 'content_fetched', 'error']
  - constraint: primary key (pmid)
  - constraint: unique(pmc_id) where pmc_id is not null
  - constraint: unique(doi) where doi is not null
  - constraint: open_access IN (true,false)
- `search_queries.json` — Materialized representation of search inputs (basic/author/journal/advanced) and their resolved PubMed query string, enabling caching and batch execution. (35 rows; fields: ['id', 'client_id', 'query_type', 'input', 'canonical_query', 'status', 'max_results', 'cache_expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'expired']
  - constraint: foreign key (client_id) references api_clients(id)
  - constraint: max_results BETWEEN 1 AND 10000
  - constraint: unique(client_id, query_type, canonical_query)
- `query_article_results.json` — Join table mapping a search query to its ranked result set of PubMed articles; supports returning titles/authors/dates/PMIDs/PMCs/DOIs and stable ordering (including batch searches). (35 rows; fields: ['id', 'query_id', 'pmid', 'rank', 'score', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded']
  - constraint: foreign key (query_id) references search_queries(id) on delete cascade
  - constraint: foreign key (pmid) references articles(pmid)
  - constraint: unique(query_id, rank)
  - constraint: unique(query_id, pmid)
- `article_relations.json` — Directed and undirected relationships between PubMed articles used by pubmed_similar, pubmed_cites, and pubmed_cited_by. Stored as edges so repeated graph queries are fast and cacheable. (29 rows; fields: ['id', 'source_pmid', 'target_pmid', 'relation_type', 'confidence', 'status', 'last_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'error']
  - constraint: foreign key (source_pmid) references articles(pmid)
  - constraint: foreign key (target_pmid) references articles(pmid)
  - constraint: source_pmid <> target_pmid
  - constraint: unique(source_pmid, target_pmid, relation_type)

## Business rules enforced by the tools

- Every tool call must create exactly one request_logs row; status must progress according to request_logs.lifecycle.transitions.
- Requests must be rejected with status=rate_limited if the client exceeds requests_per_minute or requests_per_day; such rejections must still be logged in request_logs.
- For PMID-based tools (pubmed_similar/pubmed_cites/pubmed_cited_by/pubmed_abstract/pubmed_open_access/pubmed_full_text), request_logs.target_pmid must be set and must reference an existing articles row; if absent, create an articles row as record_status='stub' before fetching upstream.
- pubmed_full_text must only return full_text when articles.open_access=true; if open_access=false, the tool must fail with a deterministic error_code (e.g., 'not_open_access') and must not populate full_text.
- Search tools (pubmed_search/pubmed_author_search/pubmed_journal_search/pubmed_advanced_search) must materialize or reuse a search_queries row keyed by (client_id, query_type, canonical_query); results must be stored in query_article_results with contiguous ranks starting at 1.
- pubmed_batch_search must create a parent request_logs row (tool_name='pubmed_batch_search') and one child request_logs row per subquery with batch_parent_request_id set; returned results must preserve the input order by associating each subquery with its corresponding child request id.
- article_relations rows of type 'cites' must be directed from citing PMID to cited PMID; 'cited_by' edges may be stored explicitly or derived, but if stored explicitly they must be consistent inverses of 'cites' for the same pair.
- Caching: if a request is served from cache (request_logs.cache_hit=true), then request_logs.response_cache_key must be non-null and the corresponding underlying data (search_queries/query_article_results or articles/article_relations) must not be expired past cache_expires_at/TTL at response time.
- Data integrity: deleting an api_clients row is not allowed while request_logs exist for that client; instead set api_clients.status='deleted'.
- articles.full_text may only be populated when articles.pmc_id is present or full_text_source='publisher' and the service marked open_access=true based on upstream license checks.