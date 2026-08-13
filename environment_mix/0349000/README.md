# Raindrop — local MCP environment

This backend stores users' bookmarked URLs (“raindrops”), organized into collections and tagged for retrieval. Core workflows are: ingesting a bookmark into a target collection with tags, and querying bookmarks via full-text search or tag filters with optional date constraints, plus fetching a user’s latest activity feed.

Repository: https://github.com/sachin-philip/raindrop.io-mcp
Homepage: https://smithery.ai/server/@sachin-philip/raindrop-io-mcp

## Datastore

- `users.json` — End-user accounts owning collections and bookmarks. In a real Raindrop-like service this maps to the authenticated account the MCP server acts on behalf of. (12 rows; fields: ['id', 'email', 'display_name', 'status', 'default_collection_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(email)
  - constraint: status in ('active','suspended','deleted')
- `collections.json` — Bookmark collections (folders). A special 'Unsorted' collection is represented by is_system=true and slug='unsorted' and can be referenced by collection_id=0 in API inputs (mapped to the user's Unsorted collection row). (12 rows; fields: ['id', 'user_id', 'title', 'slug', 'is_system', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: foreign key (user_id) references users(id)
  - constraint: unique(user_id, slug)
  - constraint: unique(user_id, title) where status != 'deleted'
  - constraint: is_system=true implies slug in ('unsorted')
- `bookmarks.json` — Saved URLs (raindrops). Supports creation via add_bookmark and retrieval via feed and searches (full-text and tag-based). (35 rows; fields: ['id', 'user_id', 'collection_id', 'url', 'title', 'description', 'content_text', 'domain', 'created_at', 'updated_at', 'status', 'source'])
  - lifecycle `status`: ['active', 'trashed', 'deleted']
  - constraint: foreign key (user_id) references users(id)
  - constraint: foreign key (collection_id) references collections(id)
  - constraint: collection.user_id must equal bookmark.user_id (ownership integrity)
  - constraint: url length between 1 and 4096
- `tags.json` — Normalized tags per user. Used to power search_by_tag and tag assignment during add_bookmark. (25 rows; fields: ['id', 'user_id', 'name', 'created_at', 'updated_at', 'status'])
  - lifecycle `status`: ['active', 'merged', 'deleted']
  - constraint: foreign key (user_id) references users(id)
  - constraint: unique(user_id, name) where status != 'deleted'
  - constraint: name length between 1 and 64
- `bookmark_tags.json` — Join table mapping bookmarks to tags. Enables fast tag filtering for search_by_tag, and tag assignment during add_bookmark. (32 rows; fields: ['id', 'bookmark_id', 'tag_id', 'user_id', 'created_at'])
  - constraint: foreign key (bookmark_id) references bookmarks(id)
  - constraint: foreign key (tag_id) references tags(id)
  - constraint: foreign key (user_id) references users(id)
  - constraint: bookmark.user_id must equal bookmark_tags.user_id

## Business rules enforced by the tools

- Tool get_latest_feed returns the most recent bookmarks for the authenticated user where bookmarks.status='active', ordered by bookmarks.created_at desc; default page size is implementation-defined (e.g., 20).
- Tool add_bookmark requires a non-empty url; if title is omitted, the system must attempt to derive title from fetched metadata, otherwise fall back to url.
- Tool add_bookmark treats collection_id=0 as the authenticated user's system Unsorted collection (collections.is_system=true and slug='unsorted'); if a non-zero collection_id is provided it must exist, be active, and belong to the authenticated user.
- Tool add_bookmark tags input is mapped by upserting tags(user_id,name) (case-folded normalization) in status='active' and creating bookmark_tags edges; duplicate tag associations are ignored via unique(bookmark_id, tag_id).
- Tool search_by_tag requires tag; it resolves the tag by normalized name within the user and returns bookmarks joined through bookmark_tags; if collection_id=0, search spans all collections owned by the user, otherwise restricts to that collection.
- Tool search_bookmarks requires query; it performs full-text matching over bookmarks.title, bookmarks.description, and bookmarks.content_text (or vendor-equivalent search index) restricted to the authenticated user's bookmarks; if collection_id=0, search spans all collections, otherwise restricts to that collection.
- Both search tools enforce count in the range 1..50 (default 10) and return at most count bookmarks ordered by relevance then created_at desc (for keyword search) or created_at desc (for tag search) unless the service defines otherwise.
- Both search tools enforce optional from_date and to_date as inclusive filters on bookmarks.created_at (date portion); from_date must be <= to_date when both provided.
- Deleted entities are not returned by any read tool: bookmarks.status in ('trashed','deleted') are excluded; collections.status='deleted' are excluded; tags.status='deleted' are excluded.
- FK integrity and ownership integrity must be enforced for all writes: a user cannot attach a bookmark to another user's collection, nor apply another user's tag to their bookmark.