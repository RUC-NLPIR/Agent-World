# MediaWiki — local MCP environment

This backend stores per-session wiki targeting plus core MediaWiki entities: pages, revisions (edit history), and files/media metadata. The main workflows are selecting a wiki base URL for a session, reading pages and revision history (optionally including source or rendered HTML), searching across pages, and creating/updating pages by appending new revisions with optimistic concurrency against a latest revision id.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@ProfessionalWiki/mediawiki-mcp-server

## Datastore

- `wiki_sessions.json` — Tracks the active target wiki for a client session so subsequent calls resolve titles/search against the correct wiki. Mirrors the tool behavior of set-wiki and provides request scoping for all other tools. (18 rows; fields: ['id', 'status', 'wiki_base_url', 'wiki_article_path', 'wiki_api_endpoint', 'wiki_rest_endpoint', 'default_content_model', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'revoked']
  - constraint: wiki_base_url must be a valid URI and normalized (lowercase host, no trailing slash unless root).
  - constraint: wiki_api_endpoint must be a valid URI ending with /w/api.php in typical installations (allow overrides).
  - constraint: wiki_rest_endpoint must be a valid URI.
  - constraint: last_used_at >= created_at
- `pages.json` — Wiki pages keyed by (wiki_base_url, title). Stores latest revision pointer and page-level metadata required for get-page, create-page, update-page, and search results. (17 rows; fields: ['id', 'wiki_base_url', 'namespace', 'title', 'prefixed_title', 'content_model', 'status', 'latest_revision_id', 'latest_revision_number', 'license_code', 'license_url', 'rendered_html_cache', 'rendered_html_revision_id', 'search_vector', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'protected', 'moved']
  - constraint: unique(wiki_base_url, prefixed_title)
  - constraint: namespace >= 0
  - constraint: content_model must be non-empty
  - constraint: If latest_revision_id is not null then latest_revision_number is not null
- `revisions.json` — Immutable page revisions (edit history). Supports get-page-history pagination, get-page latest revision info, create-page, and update-page by writing a new revision with a base revision check. (19 rows; fields: ['id', 'page_id', 'wiki_base_url', 'revision_number', 'parent_revision_number', 'status', 'comment', 'content_model', 'source_text', 'sha1', 'author_user_id', 'tags', 'created_at', 'updated_at'])
  - lifecycle `status`: ['published', 'superseded', 'reverted', 'deleted']
  - constraint: unique(page_id, revision_number)
  - constraint: revision_number > 0
  - constraint: parent_revision_number is null OR parent_revision_number < revision_number
  - constraint: tags is an array of non-empty strings
- `files.json` — Metadata for File namespace pages and their downloadable derivatives. Powers get-file by title and provides download/thumbnail/preview/original URLs. (17 rows; fields: ['id', 'page_id', 'wiki_base_url', 'title', 'status', 'mime_type', 'size_bytes', 'width', 'height', 'original_url', 'thumbnail_url', 'preview_url', 'sha1', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'missing', 'deleted']
  - constraint: unique(wiki_base_url, title)
  - constraint: size_bytes is null OR size_bytes >= 0
  - constraint: width is null OR width > 0
  - constraint: height is null OR height > 0
- `search_queries.json` — Persisted search requests and their result pointers to support auditing, caching, and enforcing limit bounds for search-page. (18 rows; fields: ['id', 'wiki_base_url', 'query', 'limit', 'status', 'result_page_ids', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'completed', 'failed']
  - constraint: query must be non-empty
  - constraint: limit between 1 and 100 inclusive
  - constraint: result_page_ids length <= limit
  - constraint: If status='failed' then error_message is not null

## Business rules enforced by the tools

- set-wiki(wikiUrl) must parse and normalize to wiki_base_url and populate wiki_api_endpoint and wiki_rest_endpoint; the session status must be active to be used by other tools.
- get-page(title, content) resolves the requested title within the active wiki_base_url by matching pages.prefixed_title; if content='withSource' return revisions.source_text for pages.latest_revision_id; if content='withHtml' return pages.rendered_html_cache only when pages.rendered_html_revision_id == pages.latest_revision_id, otherwise generate and update the cache atomically.
- get-page must include license_code/license_url and latest revision metadata (revision_number, created_at, comment, tags) sourced from revisions where revisions.id = pages.latest_revision_id.
- get-page-history(title, olderThan, newerThan, filter) must return at most 20 revisions for the page ordered by revision_number desc by default; if olderThan is provided return revisions with revision_number < olderThan; if newerThan is provided return revisions with revision_number > newerThan; olderThan and newerThan must not both be provided in the same request.
- get-page-history(filter) supports exactly one tag string; it returns only revisions where filter is contained in revisions.tags.
- search-page(query, limit) must enforce 1 <= limit <= 100; it records a row in search_queries and returns pages referenced by result_page_ids within the active wiki_base_url.
- create-page(title, source, comment, contentModel) must fail if a page with (wiki_base_url, prefixed_title) already exists; it creates pages + an initial revisions row, sets pages.latest_revision_id/latest_revision_number to the new revision, and sets pages.status='active'. If contentModel is omitted, use wiki_sessions.default_content_model.
- update-page(title, source, latestId, comment) must perform optimistic concurrency: latestId must equal pages.latest_revision_number at commit time; otherwise reject with edit conflict and do not write a revision.
- update-page creates a new revisions row with parent_revision_number=latestId, increments revision_number according to the upstream/system-of-record semantics, marks the previous latest revision status to 'superseded', and updates pages.latest_revision_id/latest_revision_number.
- get-file(title) must resolve to a pages row in File namespace (namespace=6) and return files metadata; if not found in files but a page exists, a refresh job may populate files and return status='missing' until URLs are known.
- FK integrity must be enforced: revisions.page_id must exist; files.page_id must exist and belong to the same wiki_base_url; pages.latest_revision_id must reference a revision for that same page.
- Deletion semantics: if pages.status='deleted' then get-page and get-page-history must either return a not-found/permission error or a redacted response; revisions.status may transition to 'deleted' only as part of page deletion workflows.