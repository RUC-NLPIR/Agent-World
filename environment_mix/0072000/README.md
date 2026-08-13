# BioMCP — local MCP environment

BioMCP is an API backend that brokers three external biomedical data sources: PubMed (article search/details), ClinicalTrials.gov v2 (trial search and trial module retrieval), and MyVariant.info (variant search and variant detail). The backend primarily stores normalized search requests/responses for caching, observability, and auditing, plus per-entity snapshots (articles, trials, variants) keyed by their authoritative external identifiers.

Repository: https://github.com/genomoncology/biomcp
Homepage: https://smithery.ai/server/@genomoncology/biomcp

## Datastore

- `api_clients.json` — Represents a calling application/user of the BioMCP server. Used for rate limiting, attribution, and auditing tool calls. (30 rows; fields: ['id', 'name', 'status', 'api_key_hash', 'quota_requests_per_minute', 'quota_requests_per_day', 'notes', 'created_at', 'updated_at', 'last_seen_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(api_key_hash)
  - constraint: unique(name)
  - constraint: quota_requests_per_minute between 1 and 6000
  - constraint: quota_requests_per_day between 1 and 200000
- `tool_calls.json` — Append-only log of every tool invocation, its normalized request payload, cache decisions, execution status, and response metadata. Serves auditing, debugging, and quota enforcement. (38 rows; fields: ['id', 'client_id', 'tool_name', 'status', 'request_json', 'request_canonical_json', 'request_hash', 'source_system', 'cache_mode', 'cache_ttl_seconds', 'response_format', 'response_markdown', 'response_json', 'http_status', 'error_code', 'error_message', 'upstream_latency_ms', 'created_at', 'updated_at', 'completed_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed', 'rate_limited', 'cancelled']
  - constraint: foreign key (client_id) references api_clients(id) on delete restrict
  - constraint: unique(client_id, tool_name, request_hash, created_at::date, status) not enforced (calls are append-only); indexing recommended on (tool_name, request_hash, created_at desc)
  - constraint: cache_ttl_seconds is null or between 30 and 2592000
  - constraint: http_status is null or between 100 and 599
- `pubmed_articles.json` — Locally cached snapshots of PubMed article metadata keyed by PMID. Supports article_details and enriches article_searcher results. (31 rows; fields: ['id', 'pmid', 'status', 'title', 'abstract', 'journal', 'publication_date', 'authors', 'doi', 'mesh_terms', 'keywords', 'source_url', 'raw_record_json', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'tombstoned']
  - constraint: unique(pmid)
  - constraint: pmid matches regex '^[0-9]+$'
  - constraint: doi is null or length(doi) between 6 and 255
  - constraint: source_url is null or source_url like 'https://pubmed.ncbi.nlm.nih.gov/%'
- `clinical_trials.json` — Locally cached snapshots of ClinicalTrials.gov studies keyed by NCT ID, including key modules used by trial_protocol, trial_locations, trial_outcomes, trial_references, and also used to enrich trial_searcher results. (37 rows; fields: ['id', 'nct_id', 'status', 'overall_status', 'brief_title', 'official_title', 'sponsor', 'phases', 'conditions', 'interventions', 'brief_summary', 'protocol_module_json', 'contacts_locations_module_json', 'outcomes_module_json', 'results_section_json', 'references_module_json', 'source_url', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'tombstoned']
  - constraint: unique(nct_id)
  - constraint: nct_id matches regex '^NCT[0-9]{8}$'
  - constraint: source_url is null or source_url like 'https://clinicaltrials.gov/%'
  - constraint: fetched_at <= now()
- `genetic_variants.json` — Locally cached snapshots of MyVariant.info variant annotations keyed by a canonical variant id (e.g., chr7:g.140453136A>T). Supports variant_details and enriches variant_searcher results. (37 rows; fields: ['id', 'variant_id', 'status', 'gene_symbol', 'chromosome', 'position', 'ref', 'alt', 'hgvs_c', 'hgvs_p', 'rsid', 'clinical_significance', 'frequencies_json', 'prediction_scores_json', 'raw_record_json', 'source_url', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'tombstoned']
  - constraint: unique(variant_id)
  - constraint: variant_id length between 5 and 200
  - constraint: position is null or position > 0
  - constraint: source_url is null or source_url like 'https://myvariant.info/%'

## Business rules enforced by the tools

- Every tool invocation MUST create one tool_calls row with status 'received' before execution; it MUST transition to 'running' and then exactly one terminal status in {succeeded, failed, rate_limited, cancelled}.
- Calls from api_clients with status in ('suspended','deleted') MUST be rejected and recorded as tool_calls.status='rate_limited' with error_code='CLIENT_NOT_ACTIVE'.
- Rate limits MUST be enforced per client: within any rolling 60s window, successful+failed+cancelled calls count toward quota_requests_per_minute; within any rolling 24h window they count toward quota_requests_per_day. Exceeding either MUST yield tool_calls.status='rate_limited'.
- For article_details: if the request references a PMID (resolved from context or upstream), the service MUST upsert pubmed_articles by pmid and return Markdown derived from the cached row; if upstream fails, it MAY return data from an existing non-tombstoned cached row marked stale.
- For article_searcher: the request_json MUST support lists for genes, variants, diseases, chemicals, keywords (even if empty) and be stored verbatim; the canonical form MUST normalize case/whitespace and de-duplicate list terms before hashing for cache keys.
- For trial_* tools: the input NCT ID MUST match '^NCT[0-9]{8}$' or the call MUST fail with error_code='INVALID_NCT_ID'. Successful calls MUST upsert clinical_trials and populate the corresponding module JSON field(s) required by that tool.
- For trial_searcher: tool_calls.request_json MUST store the full TrialQuery object (conditions, interventions, terms, recruiting_status, phase, geo location, date ranges, etc.) even if only a subset is forwarded upstream; response_markdown MUST include at minimum NCT ID, title, and status for each returned trial.
- For variant_details: the input variant identifier MUST be stored in tool_calls.request_json and MUST upsert genetic_variants.variant_id and raw_record_json on success; invalid identifiers MUST fail with error_code='INVALID_VARIANT_ID'.
- For variant_searcher: tool_calls.request_json MUST store the full VariantQuery (gene, hgvsp/hgvsc, rsid, region, significance, frequency ranges, prediction score filters, etc.). Any numeric ranges MUST be validated: frequencies in [0,1], score ranges must have min <= max when both set.
- Cache policy: for each tool_name the backend MUST define a TTL and set tool_calls.cache_ttl_seconds; cached entity rows (pubmed_articles/clinical_trials/genetic_variants) MUST be marked 'stale' when now() - fetched_at exceeds the TTL, and refreshed on next access unless the call is cache_mode='bypass'.