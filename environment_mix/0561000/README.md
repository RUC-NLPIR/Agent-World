# Domain Search - No API key required. — local MCP environment

This backend powers a public domain availability lookup service that normalizes a requested domain, queries one or more upstream registries/registrars for availability and pricing, and returns the latest result. It stores domain normalization, provider routing, cached check results with TTL, and provider pricing snapshots used to compute returned prices.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@szypetike/domain-search-server

## Datastore

- `domains.json` — Canonicalized domain names and parsing metadata (SLD/TLD) used for lookups and caching. (18 rows; fields: ['id', 'fqdn', 'unicode_fqdn', 'tld', 'sld', 'is_idn', 'status', 'blocked_reason', 'first_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'blocked', 'deleted']
  - constraint: unique(fqdn)
  - constraint: fqdn must be a valid normalized domain name (punycode ASCII, no scheme/path, labels 1-63 chars, total length <= 253)
  - constraint: tld != '' and sld != ''
  - constraint: status in ('active','blocked','deleted')
- `providers.json` — Upstream registry/registrar/provider definitions used to perform availability and pricing checks. (18 rows; fields: ['id', 'name', 'provider_type', 'base_url', 'supports_pricing', 'status', 'priority', 'timeout_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'degraded', 'disabled']
  - constraint: unique(name)
  - constraint: priority >= 0
  - constraint: timeout_ms between 100 and 30000
  - constraint: status in ('active','degraded','disabled')
- `provider_tld_configs.json` — Per-provider routing and pricing configuration by TLD (including fallback/coverage and default prices when upstream does not return pricing). (18 rows; fields: ['id', 'provider_id', 'tld', 'is_supported', 'currency', 'default_register_price', 'default_renew_price', 'default_transfer_price', 'created_at', 'updated_at'])
  - lifecycle `is_supported`: ['true', 'false']
  - constraint: foreign key(provider_id) references providers(id) on delete cascade
  - constraint: unique(provider_id, tld)
  - constraint: tld != ''
  - constraint: default_register_price is null or default_register_price >= 0
- `domain_checks.json` — Each availability check request/attempt for a domain. Stores provider used, computed availability, pricing returned, caching/TTL, and error details. (18 rows; fields: ['id', 'domain_id', 'requested_domain', 'provider_id', 'status', 'availability', 'currency', 'register_price', 'renew_price', 'transfer_price', 'premium', 'checked_at', 'cache_expires_at', 'provider_latency_ms', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'rejected']
  - constraint: foreign key(domain_id) references domains(id) on delete restrict
  - constraint: foreign key(provider_id) references providers(id) on delete set null
  - constraint: requested_domain length between 1 and 320
  - constraint: provider_latency_ms is null or provider_latency_ms between 0 and 30000
- `tld_price_snapshots.json` — Time-versioned pricing snapshots per provider and TLD used to answer pricing information and to audit pricing changes. (18 rows; fields: ['id', 'provider_id', 'tld', 'currency', 'register_price', 'renew_price', 'transfer_price', 'effective_at', 'source', 'created_at', 'updated_at'])
  - lifecycle `source`: ['upstream', 'configured_fallback', 'manual_override']
  - constraint: foreign key(provider_id) references providers(id) on delete cascade
  - constraint: unique(provider_id, tld, currency, effective_at)
  - constraint: register_price is null or register_price >= 0
  - constraint: renew_price is null or renew_price >= 0

## Business rules enforced by the tools

- Tool `check_domain_availability(domain)` MUST store the raw input into domain_checks.requested_domain and MUST create or reuse a domains row whose fqdn is the normalized punycode/ASCII lowercase version of `domain`.
- If the normalized domain is syntactically invalid (e.g., contains scheme/path, invalid label lengths/characters, total length > 253), the system MUST create a domain_checks row with status='rejected', provider_id=NULL, error_code='INVALID_DOMAIN'.
- If domains.status='blocked', the system MUST create a domain_checks row with status='rejected' and error_code='BLOCKED_DOMAIN'.
- Provider selection MUST choose the lowest providers.priority among providers.status in ('active','degraded') that has provider_tld_configs.is_supported=true for the domain's tld; otherwise the system MUST reject with error_code='UNSUPPORTED_TLD'.
- Before calling upstream, the service MAY serve a cached result by returning the most recent domain_checks row for the same domain_id and provider_id with status='succeeded' and cache_expires_at > now(); in that case no new upstream call is required, but a new domain_checks row SHOULD still be created to audit the request with status='succeeded' and copied result fields.
- When an upstream call is made, domain_checks MUST transition queued -> running -> (succeeded|failed).
- On success, domain_checks.status MUST be set to 'succeeded', checked_at MUST be set, availability MUST be one of ('available','unavailable','unknown'), and any returned prices MUST be stored in register_price/renew_price/transfer_price with currency set.
- If the upstream response lacks pricing and provider_tld_configs has defaults, the service MUST fill domain_checks prices from provider_tld_configs default_* fields and record a tld_price_snapshots row with source='configured_fallback'.
- If the upstream call errors or times out, domain_checks.status MUST be 'failed' with a non-null error_code (e.g., 'UPSTREAM_TIMEOUT', 'UPSTREAM_ERROR') and error_message, and provider_latency_ms MUST be recorded when measurable.
- All prices stored MUST be non-negative numbers; currency MUST be consistent between domain_checks and the selected provider_tld_configs/tld_price_snapshots for the same provider/tld at the time of the check.