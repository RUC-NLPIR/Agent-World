# Wikipedia Integration Server — local MCP environment

This backend powers a Wikipedia integration API that searches for articles by query and retrieves article content, summaries, sections, and links. It also stores derived artifacts (query-tailored summaries, section summaries, extracted key facts, related topics) with caching and lifecycle/status so repeated tool calls can be served quickly while respecting refresh and quota rules.

Repository: https://github.com/geobio/wikipedia-mcp
Homepage: https://smithery.ai/server/@geobio/wikipedia-mcp

## Datastore

- `api_clients.json` — Represents an API consumer (user/app) and its quota/limits for calling the Wikipedia Integration Server tools. (20 rows; fields: ['id', 'name', 'status', 'daily_request_limit', 'burst_rps_limit', 'default_language', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: daily_request_limit >= 0
  - constraint: burst_rps_limit >= 0
  - constraint: default_language matches regex '^[a-z]{2,3}(-[a-z0-9]+)?$'
- `api_keys.json` — Authentication credentials for API clients; used for tracking and enforcing per-key usage. (32 rows; fields: ['id', 'client_id', 'key_name', 'token_hash', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(client_id, key_name)
  - constraint: unique(token_hash)
  - constraint: FK(client_id) references api_clients(id) on delete cascade
- `articles.json` — Canonical cache of Wikipedia pages by normalized title and language; stores content, summary, links, and sections metadata for serving get_article/get_summary/get_links/get_sections. (36 rows; fields: ['id', 'language', 'title', 'normalized_title', 'page_id', 'revision_id', 'status', 'full_text', 'summary_text', 'sections', 'links', 'categories', 'fetched_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'missing', 'stale', 'error']
  - constraint: unique(language, normalized_title)
  - constraint: page_id is null or page_id > 0
  - constraint: revision_id is null or revision_id > 0
  - constraint: expires_at is null or expires_at >= fetched_at
- `search_queries.json` — Stores Wikipedia search calls (search_wikipedia) and their results for analytics, caching, and rate limiting. (39 rows; fields: ['id', 'client_id', 'api_key_id', 'language', 'query', 'limit', 'status', 'result_count', 'results', 'error_message', 'requested_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: FK(client_id) references api_clients(id)
  - constraint: FK(api_key_id) references api_keys(id)
  - constraint: limit between 1 and 50
  - constraint: result_count is null or result_count >= 0
- `derived_artifacts.json` — Stores computed outputs derived from an article (query-tailored summaries, section summaries, extracted key facts, related topics) for caching and reproducibility. (34 rows; fields: ['id', 'client_id', 'article_id', 'artifact_type', 'query', 'section_title', 'topic_within_article', 'max_length', 'count', 'status', 'output_text', 'output_items', 'computed_at', 'expires_at', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['computing', 'available', 'stale', 'error']
  - constraint: FK(client_id) references api_clients(id)
  - constraint: FK(article_id) references articles(id) on delete cascade
  - constraint: max_length is null or max_length between 50 and 2000
  - constraint: count is null or count between 1 and 50

## Business rules enforced by the tools

- Tool search_wikipedia(query, limit) MUST create a search_queries row with query and limit, set status queued->running->(succeeded|failed), and store results (up to limit) on success.
- Tool get_article(title) MUST resolve (language, normalized_title) to an articles row; if missing or stale/expired, it MUST refresh from Wikipedia and transition status to available or missing/error accordingly.
- Tool get_summary(title) MUST return articles.summary_text when articles.status=available and summary_text is not null; otherwise it MUST refresh the article cache.
- Tool get_sections(title) MUST return articles.sections when available; if sections is null or cache expired, it MUST refresh.
- Tool get_links(title) MUST return articles.links when available; if links is null or cache expired, it MUST refresh.
- Tool summarize_article_for_query(title, query, max_length) MUST create or reuse a derived_artifacts row with artifact_type='query_summary' keyed by (client_id, article_id, query, max_length); it MUST store the generated output_text and set status to available on success.
- Tool summarize_article_section(title, section_title, max_length) MUST create or reuse a derived_artifacts row with artifact_type='section_summary' keyed by (client_id, article_id, section_title, max_length); it MUST store output_text and set status to available on success.
- Tool extract_key_facts(title, topic_within_article, count) MUST create or reuse a derived_artifacts row with artifact_type='key_facts' keyed by (client_id, article_id, topic_within_article, count); it MUST store output_items with at most count items.
- Tool get_related_topics(title, limit) MUST create or reuse a derived_artifacts row with artifact_type='related_topics' keyed by (client_id, article_id, count=limit) and store output_items with at most limit items.
- Requests authenticated with an api_keys token MUST belong to an api_clients row in status=active; api_keys.status must be active or the request is rejected.
- For each api_client, total successful tool calls per UTC day MUST NOT exceed daily_request_limit; once exceeded, further tool calls are rejected with a quota error.
- For caching: articles.expires_at and derived_artifacts.expires_at define staleness; reads SHOULD serve available non-expired records and otherwise trigger recompute/refetch, transitioning status to stale/computing as appropriate.
- All title lookups MUST use normalized_title for uniqueness, but tools MUST preserve and return the original canonical/display title from articles.title when available.