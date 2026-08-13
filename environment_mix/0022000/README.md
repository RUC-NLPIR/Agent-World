# Sitemap MCP — local MCP environment

This backend stores discovered sitemaps for target websites, the hierarchical sitemap index/tree structure, and the individual URL pages extracted from sitemap XML. Main workflows are: ingest/parse sitemap content (from a fetched URL or directly provided XML), persist a sitemap tree and pages, and serve read-only endpoints for tree, pages (with pagination/filtering), and aggregate statistics.

Repository: https://github.com/mugoosse/sitemap-mcp-server
Homepage: https://smithery.ai/server/@mugoosse/sitemap

## Datastore

- `sites.json` — Canonical representation of a website/domain being analyzed for sitemaps. Used to group multiple sitemap documents and their extracted pages. (18 rows; fields: ['id', 'canonical_url', 'host', 'robots_txt_url', 'status', 'last_discovered_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(host)
  - constraint: canonical_url LIKE 'http%://%'
  - constraint: host = lower(host)
- `sitemaps.json` — A sitemap document (either sitemapindex or urlset) associated with a site. Stores source, raw content fingerprint, and parsing outcomes. (17 rows; fields: ['id', 'site_id', 'parent_sitemap_id', 'source_type', 'source_url', 'content_sha256', 'content_bytes', 'content_type', 'sitemap_kind', 'status', 'parsed_at', 'error_code', 'error_message', 'discovered_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'parsed', 'failed', 'superseded']
  - constraint: foreign key(site_id) references sites(id) on delete restrict
  - constraint: foreign key(parent_sitemap_id) references sitemaps(id) on delete set null
  - constraint: discovered_count >= 0
  - constraint: content_bytes is null or content_bytes >= 0
- `sitemap_nodes.json` — Materialized tree structure for a site's sitemap(s). Each node represents either a sitemap document node or a URL leaf node reference; used to serve get_sitemap_tree quickly. (20 rows; fields: ['id', 'site_id', 'root_sitemap_id', 'parent_node_id', 'node_type', 'sitemap_id', 'page_id', 'label', 'depth', 'child_count', 'created_at', 'updated_at'])
  - lifecycle `node_type`: ['sitemap', 'url']
  - constraint: foreign key(site_id) references sites(id) on delete cascade
  - constraint: foreign key(root_sitemap_id) references sitemaps(id) on delete cascade
  - constraint: foreign key(parent_node_id) references sitemap_nodes(id) on delete cascade
  - constraint: depth >= 0
- `sitemap_pages.json` — Individual URL entries extracted from urlset sitemaps, including optional sitemap metadata such as lastmod/changefreq/priority. Supports filtering and cursor-based pagination for get_sitemap_pages. (18 rows; fields: ['id', 'site_id', 'sitemap_id', 'url', 'url_hash', 'path', 'lastmod', 'changefreq', 'priority', 'discovered_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: foreign key(site_id) references sites(id) on delete cascade
  - constraint: foreign key(sitemap_id) references sitemaps(id) on delete cascade
  - constraint: unique(site_id, url_hash)
  - constraint: priority is null or (priority >= 0.0 and priority <= 1.0)
- `parse_jobs.json` — Tracks parsing operations (including direct content parsing) used to build sitemaps/pages. Enables stats freshness, retry logic, and auditability for the parse_sitemap_content tool and any implicit discovery parsing. (18 rows; fields: ['id', 'site_id', 'input_type', 'input_url', 'input_content_sha256', 'status', 'started_at', 'finished_at', 'result_sitemap_id', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(site_id) references sites(id) on delete set null
  - constraint: foreign key(result_sitemap_id) references sitemaps(id) on delete set null
  - constraint: input_type='url' implies input_url is not null
  - constraint: input_type='content' implies input_content_sha256 is not null

## Business rules enforced by the tools

- get_sitemap_tree reads from sitemap_nodes filtered by site_id (derived from a configured default site or most-recent active site) and root_sitemap_id; nodes must form an acyclic parent_node_id hierarchy within the same root_sitemap_id.
- get_sitemap_pages reads from sitemap_pages where status='active' and site_id matches the requested/derived site; pagination uses a stable cursor over (discovered_at, id) or (url_hash, id) with deterministic ordering.
- get_sitemap_pages optional filtering must be implementable via fields: by sitemap_id, by path prefix (path LIKE 'prefix%'), by lastmod range (lastmod >= / <=), and by changefreq/priority when present.
- get_sitemap_stats aggregates over sitemaps, sitemap_nodes, and sitemap_pages for a site: total sitemaps, total pages, max depth, count by sitemap_kind, count by changefreq, last_discovered_at, and failure counts from parse_jobs/sitemaps where status='failed'.
- parse_sitemap_content creates a parse_jobs row, writes a sitemaps row with source_type='content' and content_sha256, and upserts extracted sitemap_pages (unique(site_id,url_hash)); it also builds/refreshes sitemap_nodes for the affected root_sitemap_id in a single logical transaction.
- When a sitemap document is re-parsed and content_sha256 changes, the previous sitemaps row for the same (site_id, source_url) must transition to status='superseded' and the new row becomes status='parsed'.
- A sitemap_pages row cannot be inserted unless its sitemap_id refers to a sitemaps row with sitemap_kind='urlset' and status='parsed'.
- Priority values outside [0.0, 1.0] are rejected; invalid changefreq values are rejected; malformed URLs (non-http/https) are rejected.
- Deleting/disable of a site prevents new parse_jobs from being queued for that site; reads may still be allowed for disabled but not deleted sites depending on deployment policy.
- All status transitions must follow the declared lifecycle transitions; direct updates that skip states (e.g., queued -> succeeded) are rejected.