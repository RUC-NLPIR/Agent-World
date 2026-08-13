# Brasil API — local MCP environment

This backend powers a read-heavy aggregation API for Brazilian public/reference datasets (CEP, CNPJ, banks, DDD/IBGE geography, exchange rates, and .br domain status). It stores normalized reference entities and time-series rates, plus a request log to support auditing, caching decisions, and operational rate-limiting/quotas.

Repository: https://github.com/guilhermelirio/brasil-api-mcp
Homepage: https://smithery.ai/server/@guilhermelirio/brasil-api-mcp

## Datastore

- `api_clients.json` — API consumers (first/third-party) and their credentials, quotas, and lifecycle status. Used to authenticate requests and enforce per-client rate limits/usage quotas across all tools. (31 rows; fields: ['id', 'name', 'api_key_hash', 'status', 'requests_per_minute_limit', 'requests_per_day_limit', 'contact_email', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(api_key_hash)
  - constraint: unique(name)
  - constraint: requests_per_minute_limit >= 1
  - constraint: requests_per_day_limit IS NULL OR requests_per_day_limit >= 1
- `api_requests.json` — Append-only request/response metadata for all tools. Supports auditing, abuse detection, SLA monitoring, and enables cache warm-up strategies. (33 rows; fields: ['id', 'client_id', 'tool_name', 'input_params', 'normalized_cache_key', 'cache_hit', 'http_status', 'error_code', 'latency_ms', 'response_ref', 'requested_at', 'created_at', 'updated_at'])
  - lifecycle `http_status`: ['200', '400', '401', '403', '404', '429', '500', '502', '503']
  - constraint: fk(client_id) references api_clients(id)
  - constraint: unique(normalized_cache_key, requested_at)
  - constraint: http_status >= 100 AND http_status <= 599
  - constraint: latency_ms >= 0
- `reference_geo.json` — Geographic and administrative reference data used by CEP and DDD lookups and IBGE endpoints: states (UF), municipalities, DDD ranges, and CEP address records. (31 rows; fields: ['id', 'entity_type', 'status', 'state_ibge_code', 'state_uf', 'state_name', 'municipality_ibge_code', 'municipality_name', 'parent_state_id', 'ddd', 'ddd_cities', 'cep', 'street', 'neighborhood', 'city', 'service_provider', 'source_last_verified_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded']
  - constraint: chk(entity_type in ('state','municipality','ddd','cep'))
  - constraint: chk(status in ('active','superseded'))
  - constraint: unique(state_uf) where entity_type='state' and status='active'
  - constraint: unique(state_ibge_code) where entity_type='state' and status='active'
- `reference_finance.json` — Financial reference data and time-series values used by bank and exchange-rate tools: banks, currencies, and daily exchange rates. (30 rows; fields: ['id', 'entity_type', 'status', 'bank_code', 'bank_name', 'bank_ispb', 'currency_code', 'currency_name', 'currency_country', 'rate_date', 'rate_value', 'rate_kind', 'source_last_verified_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive', 'superseded']
  - constraint: chk(entity_type in ('bank','currency','fx_rate'))
  - constraint: unique(bank_code) where entity_type='bank' and status='active'
  - constraint: unique(currency_code) where entity_type='currency' and status='active'
  - constraint: unique(currency_code, rate_date, rate_kind) where entity_type='fx_rate' and status='active'
- `reference_registry.json` — Registry-like entities: CNPJ company snapshots and Registro.br domain availability/status checks (cached results with TTL). (31 rows; fields: ['id', 'entity_type', 'status', 'cnpj', 'legal_name', 'trade_name', 'company_situation', 'opened_at', 'address', 'primary_activity', 'secondary_activities', 'raw_payload', 'domain', 'domain_available', 'domain_status_text', 'checked_at', 'expires_at', 'source_last_verified_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'superseded']
  - constraint: chk(entity_type in ('cnpj_company','br_domain_check'))
  - constraint: unique(cnpj) where entity_type='cnpj_company' and status='active'
  - constraint: unique(domain) where entity_type='br_domain_check' and status='active'
  - constraint: chk(cnpj is null or cnpj ~ '^\d{14}$')

## Business rules enforced by the tools

- All tool invocations must create an api_requests row with tool_name matching one of the supported tools and input_params containing exactly the validated JSON-Schema parameters (no additional properties).
- Requests must be rejected (401/403) when api_clients.status != 'active'; every rejected request is still logged in api_requests with the correct http_status.
- Rate limiting must enforce api_clients.requests_per_minute_limit per client across all tools; violations return 429 and are logged with cache_hit=false.
- Tool 'cep-search' must validate input cep as exactly 8 digits; it should read from reference_geo where entity_type='cep' and cep matches; if not found locally, the service may fetch upstream and upsert an active CEP record (superseding any older active record).
- Tool 'ddd-info' must validate ddd as exactly 2 digits; it should read from reference_geo where entity_type='ddd' and ddd matches; returned state and cities must be derived from state_uf and ddd_cities fields.
- Tools 'ibge-states-list' and 'ibge-state-search' must read state records from reference_geo where entity_type='state' and status='active'; ibge-state-search must match either state_uf or state_ibge_code.
- Tool 'ibge-municipalities-list' must require uf; it returns municipalities from reference_geo where entity_type='municipality' and state_uf equals the requested uf and status='active'.
- Tools 'bank-list' and 'bank-search' must read bank records from reference_finance where entity_type='bank' and status='active'; bank-search matches bank_code exactly.
- Tool 'cambio-currencies-list' must read currency records from reference_finance where entity_type='currency' and status='active'.
- Tool 'cambio-rate' must require currency and date; date must match YYYY-MM-DD; it returns a record from reference_finance where entity_type='fx_rate', currency_code matches, and rate_date equals the requested date; if upstream returns a different business day, the persisted rate_date must be the actual returned date while api_requests.response_ref must reflect both requested and effective dates.
- Tool 'cnpj-search' must validate cnpj as exactly 14 digits; it reads from reference_registry where entity_type='cnpj_company' and cnpj matches and status='active'; if fetched upstream, store raw_payload for forward compatibility and update source_last_verified_at.
- Tool 'registrobr-domain-check' must normalize input to a canonical domain string (lowercase, strip scheme/path; ensure .br handling per implementation); it may serve cached results from reference_registry where entity_type='br_domain_check', domain matches, status='active', and expires_at > now; otherwise it must refresh upstream and set checked_at and expires_at based on a configured TTL.