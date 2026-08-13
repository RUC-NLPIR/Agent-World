# LottieFiles Server — local MCP environment

This backend stores a catalog of Lottie animations and the metadata required to search, rank, and retrieve detailed animation information (including Lottie JSON, previews, and tags). Core workflows are: indexing/publishing animations, searching with pagination, fetching an animation’s details by id, and listing popular animations via a rolling popularity score.

Repository: https://github.com/junmer/mcp-server-lottiefiles
Homepage: https://smithery.ai/server/@junmer/mcp-server-lottiefiles

## Datastore

- `animations.json` — Primary catalog of Lottie animations with metadata used for search and detail retrieval. (18 rows; fields: ['id', 'slug', 'title', 'description', 'status', 'visibility', 'lottie_json', 'lottie_json_url', 'preview_image_url', 'preview_gif_url', 'width', 'height', 'duration_ms', 'fps', 'file_size_bytes', 'license', 'author_name', 'source_url', 'search_document', 'published_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'published', 'unlisted', 'deleted']
  - constraint: unique(slug) where slug is not null
  - constraint: status in ('draft','published','unlisted','deleted')
  - constraint: visibility in ('public','private')
  - constraint: width is null or width > 0
- `tags.json` — Controlled vocabulary and free-form tags used for filtering and search relevance. (18 rows; fields: ['id', 'name', 'normalized_name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated']
  - constraint: unique(normalized_name)
  - constraint: length(name) between 1 and 64
- `animation_tags.json` — Many-to-many join between animations and tags. Powers tag search and tag lists on animation details. (18 rows; fields: ['id', 'animation_id', 'tag_id', 'source', 'created_at', 'updated_at'])
  - constraint: foreign key(animation_id) references animations(id) on delete cascade
  - constraint: foreign key(tag_id) references tags(id) on delete restrict
  - constraint: unique(animation_id, tag_id)
  - constraint: source in ('author','system','moderator','import')
- `animation_popularity_daily.json` — Daily rollups used to compute 'popular' rankings (downloads/likes/views) and serve get_popular_animations efficiently. (18 rows; fields: ['id', 'animation_id', 'day', 'views', 'likes', 'downloads', 'popularity_score', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active']
  - constraint: foreign key(animation_id) references animations(id) on delete cascade
  - constraint: unique(animation_id, day)
  - constraint: views >= 0
  - constraint: likes >= 0
- `search_queries.json` — Audit log of search requests for analytics, relevance tuning, and abuse detection. Supports pagination parameters and query strings from search_animations and get_popular_animations. (18 rows; fields: ['id', 'tool', 'query', 'page', 'limit', 'result_count', 'request_ip', 'user_agent', 'created_at', 'updated_at'])
  - lifecycle `status`: ['recorded']
  - constraint: page >= 1
  - constraint: limit between 1 and 100
  - constraint: result_count is null or result_count >= 0
  - constraint: tool in ('search_animations','get_popular_animations')

## Business rules enforced by the tools

- search_animations(query,page,limit) MUST filter animations where status in ('published','unlisted') and visibility='public' and match query against animations.title, animations.description, tags.name via animations.search_document and/or joins to animation_tags/tags; it MUST paginate using page>=1 and 1<=limit<=100.
- get_animation_details(id) MUST return 404/not_found if animations.id does not exist or animations.status='deleted' or animations.visibility!='public' (unless an internal bypass flag exists outside this tool surface). It MUST include the animation’s lottie_json or lottie_json_url, preview URLs, and tags derived from animation_tags -> tags where tags.status='active'.
- get_popular_animations(page,limit) MUST paginate using page>=1 and 1<=limit<=100 and MUST sort by a popularity signal derived from animation_popularity_daily over a recent window (e.g., last 7/30 days), excluding animations where status='deleted' or visibility!='public'.
- Tag assignment MUST enforce unique(animation_id, tag_id) and refuse links to tags with status='deprecated' for new assignments (existing links may remain for historical reasons).
- An animation MUST NOT transition out of 'deleted' status; publishing MUST set published_at; published/unlisted animations MUST have either lottie_json or lottie_json_url present.
- All foreign keys MUST be enforced: deleting an animation MUST cascade delete animation_tags and animation_popularity_daily rows; deleting a tag MUST be restricted while referenced by any animation_tags row.