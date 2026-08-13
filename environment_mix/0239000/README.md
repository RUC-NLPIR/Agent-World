# App Market Intelligence — local MCP environment

This backend powers an app market intelligence API by caching and serving normalized metadata about mobile apps from the Apple App Store and Google Play, plus developer profiles, reviews, ratings, versions, privacy/datasafety, permissions, and similarity relations. Primary workflows are (1) executing market queries (search/suggest/list) and storing their results for reuse and analytics, and (2) fetching app-centric details (details/ratings/reviews/etc.) into a per-store, per-locale snapshot model to serve read endpoints efficiently with auditability and quota enforcement.

Repository: https://github.com/JiantaoFu/AppInsightMCP
Homepage: https://smithery.ai/server/@JiantaoFu/appinsightmcp

## Datastore

- `api_clients.json` — API consumers (workspaces/projects) and their authentication + quota configuration used to authorize and rate-limit all tools. (18 rows; fields: ['id', 'name', 'api_key_hash', 'status', 'plan', 'daily_request_limit', 'daily_request_used', 'daily_window_start', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(api_key_hash)
  - constraint: unique(name)
  - constraint: daily_request_limit >= 0
  - constraint: daily_request_used >= 0
- `apps.json` — Canonical app identities across stores plus stable identifiers used for lookups (App Store numeric id, App Store bundle id, Google Play package name). Does not include locale-specific text; those live in app_store_listings. (18 rows; fields: ['id', 'store', 'app_store_numeric_id', 'bundle_id', 'google_play_app_id', 'canonical_url', 'status', 'first_seen_at', 'last_refreshed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed', 'tombstoned']
  - constraint: store in ('app_store','google_play')
  - constraint: ((store='app_store') implies (app_store_numeric_id is not null or bundle_id is not null))
  - constraint: ((store='google_play') implies (google_play_app_id is not null))
  - constraint: unique(store, app_store_numeric_id) where app_store_numeric_id is not null
- `developers.json` — Developer/publisher identities by store, used to support developer listing tools and to link apps to developers. (18 rows; fields: ['id', 'store', 'app_store_artist_id', 'google_play_developer_id', 'name', 'store_url', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'merged', 'removed']
  - constraint: unique(store, app_store_artist_id) where app_store_artist_id is not null
  - constraint: unique(store, google_play_developer_id) where google_play_developer_id is not null
- `app_store_listings.json` — Per-app, per-locale (country+language) snapshots of store-visible metadata and subresources needed by details/ratings/reviews/version-history/privacy/permissions/datasafety tools. (18 rows; fields: ['id', 'app_id', 'developer_id', 'country', 'lang', 'title', 'summary', 'description', 'description_html', 'icon_url', 'store_url', 'price_usd', 'currency', 'price_text', 'is_free', 'genres', 'genre_ids', 'primary_genre', 'primary_genre_id', 'content_rating', 'installs', 'min_installs', 'max_installs', 'score', 'score_text', 'ratings_total', 'ratings_histogram', 'version_history', 'privacy_details', 'permissions', 'data_safety', 'status', 'source_fetched_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['fresh', 'stale', 'refreshing', 'failed']
  - constraint: unique(app_id, country, lang)
  - constraint: country matches '^[a-zA-Z]{2}$'
  - constraint: char_length(lang) between 2 and 10
  - constraint: price_usd is null or price_usd >= 0
- `reviews.json` — Normalized app reviews fetched from App Store and Google Play, keyed by upstream review id and scoped by locale parameters to support pagination/sorting constraints. (18 rows; fields: ['id', 'app_id', 'store', 'country', 'lang', 'upstream_review_id', 'user_name', 'user_url', 'user_image', 'version', 'score', 'score_text', 'title', 'text', 'review_url', 'reviewed_at', 'updated_at_source', 'thumbs_up', 'developer_reply_text', 'developer_reply_date', 'fetch_sort', 'status', 'source_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: unique(store, upstream_review_id, app_id)
  - constraint: country matches '^[a-zA-Z]{2}$'
  - constraint: char_length(lang) between 2 and 10
  - constraint: score between 1 and 5
- `market_queries.json` — Audit log + cache index of query executions for search/suggest/list/similar/developer tools, including request parameters and normalized result references to apps/developers. (20 rows; fields: ['id', 'client_id', 'tool_name', 'request_params', 'normalized_store', 'term', 'collection', 'category', 'age', 'country', 'lang', 'page', 'num', 'sort', 'price_filter', 'full_detail', 'ids_only', 'ratings_flag', 'paginate', 'next_pagination_token', 'short', 'subject_app_id', 'subject_developer_id', 'result_app_ids', 'result_terms', 'result_categories', 'status', 'error_message', 'cache_key', 'cache_hit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'failed']
  - constraint: unique(cache_key)
  - constraint: page is null or page >= 1
  - constraint: num is null or num >= 1
  - constraint: ((tool_name='app-store-reviews') implies (page is null or (page >= 1 and page <= 10)))

## Business rules enforced by the tools

- All tool invocations must be authenticated to an api_clients row in status='active'; otherwise reject.
- Before executing any tool, increment api_clients.daily_request_used atomically; if it would exceed daily_request_limit, reject with quota exceeded and do not call upstream.
- For app-store-details/app-store-reviews/app-store-similar/app-store-ratings: either numeric id or appId (bundle id) must be provided; service must resolve to a single apps row (store='app_store') or create it if missing, then proceed.
- For google-play-details/google-play-reviews/google-play-similar/google-play-permissions/google-play-datasafety: appId must be provided and resolve/create a single apps row (store='google_play').
- For app-store-developer: devId must resolve/create a developers row with store='app_store' and app_store_artist_id=devId; for google-play-developer: devId must resolve/create a developers row with store='google_play' and google_play_developer_id=devId.
- Locale-aware endpoints must read/write app_store_listings keyed by (app_id,country,lang); if lang is omitted by the caller, the service must compute a deterministic lang for that country and still persist it in app_store_listings.lang.
- app-store-reviews enforces page in [1..10] and sort in {'recent','helpful'}; google-play-reviews enforces sort in {'newest','rating','helpfulness'}.
- google-play-reviews: if paginate=true, num is ignored and the service returns a nextPaginationToken when available; if paginate=false, nextPaginationToken must be absent/ignored.
- app-store-list: num must be <= 200; app-store-search default num=50; google-play-search num must be <= 250; any higher values must be clamped or rejected per implementation policy.
- When a tool returns apps, the service should upsert apps and app_store_listings for returned items (best-effort) and store ordered apps.id into market_queries.result_app_ids.
- google-play-categories must return the canonical static list; cache it in market_queries.result_categories and do not require upstream persistence elsewhere.
- Snapshot freshness: app_store_listings.status transitions must follow lifecycle rules; a listing with expires_at < now() must be treated as stale and refreshed before serving fullDetail/details-dependent subresources when possible.
- reviews rows must be deduplicated by unique(store, upstream_review_id, app_id); repeated fetches update mutable fields (thumbs_up, developer_reply_text/date, updated_at_source) and source_fetched_at.