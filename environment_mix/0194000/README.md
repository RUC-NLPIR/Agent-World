# Package Registry Server — local MCP environment

This backend powers a multi-registry package lookup and search API spanning Cargo, Go modules, NPM, NuGet, and PyPI. It stores normalized package identities per ecosystem, their versions, and cached upstream metadata/search results to serve low-latency reads while periodically refreshing from upstream registries.

Repository: https://github.com/ardyfeb/package-registry-mcp
Homepage: https://smithery.ai/server/@ardyfeb/package-registry-mcp

## Datastore

- `ecosystems.json` — Supported package ecosystems/registries (Cargo, Go, NPM, NuGet, PyPI) and their upstream endpoints/config used by fetchers. (12 rows; fields: ['id', 'code', 'display_name', 'base_url', 'supports_search', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'degraded', 'disabled']
  - constraint: unique(code)
  - constraint: base_url must be a valid absolute URL
  - constraint: supports_search must be true for ecosystems that expose search tools (cargo, npm, nuget)
- `packages.json` — Canonical package/module identity within an ecosystem. This is what detail and versions endpoints resolve by name/module. (37 rows; fields: ['id', 'ecosystem_id', 'package_key', 'package_key_original', 'homepage_url', 'repository_url', 'description', 'latest_version', 'downloads_total', 'metadata_json', 'cache_etag', 'cache_last_fetched_at', 'cache_expires_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'not_found', 'deprecated', 'yanked', 'blocked']
  - constraint: unique(ecosystem_id, package_key)
  - constraint: package_key length >= 1
  - constraint: downloads_total is null or downloads_total >= 0
  - constraint: latest_version is null or length(latest_version) >= 1
- `package_versions.json` — Per-package version records used by list-versions tools and to compute latest_version; includes optional upstream metadata per version. (30 rows; fields: ['id', 'package_id', 'version', 'published_at', 'downloads', 'integrity', 'metadata_json', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['published', 'yanked', 'retracted', 'unknown']
  - constraint: unique(package_id, version)
  - constraint: version length >= 1
  - constraint: downloads is null or downloads >= 0
  - constraint: published_at is null or published_at <= now()
- `search_queries.json` — Stored search requests and their cached results per ecosystem to serve search tools with consistent ordering and TTL-based refresh. (33 rows; fields: ['id', 'ecosystem_id', 'query', 'normalized_query', 'requested_limit', 'result_count', 'upstream_latency_ms', 'cache_last_fetched_at', 'cache_expires_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'refreshing', 'failed']
  - constraint: unique(ecosystem_id, normalized_query, requested_limit)
  - constraint: length(query) >= 1
  - constraint: requested_limit between 1 and 100
  - constraint: result_count is null or result_count >= 0
- `search_results.json` — Materialized search results mapping a stored search query to packages (and ranking), enabling fast list responses and reproducibility. (28 rows; fields: ['id', 'search_query_id', 'package_id', 'rank', 'score', 'snippet', 'created_at', 'updated_at'])
  - constraint: unique(search_query_id, rank)
  - constraint: unique(search_query_id, package_id)
  - constraint: rank >= 1
  - constraint: score is null or score >= 0

## Business rules enforced by the tools

- Tool parameter mapping: all tools that take {name} resolve packages.package_key within the corresponding ecosystem (cargo/npm/nuget/pypi); tools that take {module} resolve packages.package_key within the golang ecosystem.
- For get-*-package-details: if no packages row exists for (ecosystem_id, package_key), the service must attempt an upstream fetch; on upstream 404 it must upsert packages with status=not_found and set cache_last_fetched_at; on success it must upsert status=active and store metadata_json.
- For list-*-package-versions: the service must return package_versions for the resolved package ordered by published_at desc NULLS LAST then version desc, limited by the tool's limit (1..1000). If versions are stale (packages.cache_expires_at < now()), refresh from upstream before returning when possible.
- For search-*-packages: the service must enforce limit within 1..100 and query length >= 1; it should serve from cached search_queries/search_results when status=fresh and cache_expires_at >= now(), otherwise transition to refreshing and repopulate from upstream, then set status=fresh.
- FK integrity: package_versions.package_id must reference an existing packages.id; search_results must reference existing search_queries.id and packages.id; deletes of packages with dependent versions/results are restricted (must delete children first) or handled via cascading delete explicitly.
- Uniqueness and normalization: packages.package_key must be normalized consistently per ecosystem (e.g., trim; NPM lowercased; NuGet case-insensitive key) such that unique(ecosystem_id, package_key) prevents duplicate identities.
- Status transitions must follow declared lifecycle transitions; in particular package_versions.status cannot transition out of retracted, and ecosystems.status=disabled must prevent refreshing caches for that ecosystem (serve stale cache if present, otherwise fail).
- Numeric bounds from tool schemas must be enforced at write time to caches: search_queries.requested_limit must be in [1,100]; list-versions limit is applied at read time but stored per-cache entries must not exceed 100 for search tools.
- Cache TTL policy: when a cached entry is refreshed successfully, cache_last_fetched_at must be set to now() and cache_expires_at must be set to now()+TTL (TTL configurable per ecosystem). If refresh fails, set search_queries.status=failed and retain the previous cached results if any.