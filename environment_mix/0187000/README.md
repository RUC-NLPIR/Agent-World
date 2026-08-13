# Raindrop.io Bookmark Manager — local MCP environment

This backend stores users' bookmark collections (folders) and raindrops (bookmarks), including hierarchy, visibility, and trash lifecycle. Core workflows include listing/creating/updating/deleting collections, retrieving/updating single or many raindrops (including moving between collections and bulk tagging), and computing tags per collection or globally. Deletion is soft-to-trash first, with a separate operation to permanently purge trash.

Repository: https://github.com/ddltn/raindrop-mcp-python
Homepage: https://smithery.ai/server/@ddltn/raindrop-mcp-python

## Datastore

- `accounts.json` — Represents a Raindrop.io user account used to scope all collections, raindrops, and tags. (12 rows; fields: ['id', 'email', 'display_name', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(email) where email is not null
  - constraint: status in ('active','suspended','deleted')
- `collections.json` — Bookmark collections (folders). Supports root collections and nested child collections, including view settings and public visibility. Deleting a collection moves its raindrops to Trash. (31 rows; fields: ['id', 'account_id', 'parent_id', 'title', 'view', 'is_public', 'expanded', 'sort_order', 'status', 'created_at', 'updated_at', 'deleted_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key(account_id) references accounts(id) on delete restrict
  - constraint: foreign key(parent_id) references collections(id) on delete restrict
  - constraint: parent_id is null or (select account_id from collections p where p.id = parent_id) = account_id
  - constraint: view in ('list','grid','masonry','simple')
- `raindrops.json` — Bookmarks (raindrops). Supports collection assignment, favorites, tags via join table, cover images, and trash lifecycle. Also supports special virtual collections: all (collection_id=0), unsorted (collection_id=-1), and trash (collection_id=-99) via status fields rather than real collection rows. (34 rows; fields: ['id', 'account_id', 'collection_id', 'title', 'excerpt', 'link', 'domain', 'important', 'cover_url', 'type', 'order', 'status', 'trashed_at', 'created_at', 'updated_at', 'last_accessed_at'])
  - lifecycle `status`: ['active', 'trashed', 'deleted']
  - constraint: foreign key(account_id) references accounts(id) on delete restrict
  - constraint: foreign key(collection_id) references collections(id) on delete set null
  - constraint: collection_id is null or (select account_id from collections c where c.id = collection_id) = account_id
  - constraint: order >= 0
- `tags.json` — Normalized tags per account. Tags can be listed globally or per collection by joining through raindrops and raindrop_tags. (30 rows; fields: ['id', 'account_id', 'name', 'name_normalized', 'created_at', 'updated_at'])
  - constraint: foreign key(account_id) references accounts(id) on delete restrict
  - constraint: unique(account_id, name_normalized)
  - constraint: length(name_normalized) between 1 and 64
- `raindrop_tags.json` — Join table assigning tags to raindrops. Enables get_tags (global or per-collection) and updating tags for one or many raindrops. (31 rows; fields: ['id', 'account_id', 'raindrop_id', 'tag_id', 'created_at', 'updated_at'])
  - constraint: foreign key(account_id) references accounts(id) on delete restrict
  - constraint: foreign key(raindrop_id) references raindrops(id) on delete cascade
  - constraint: foreign key(tag_id) references tags(id) on delete cascade
  - constraint: unique(raindrop_id, tag_id)

## Business rules enforced by the tools

- get_root_collections returns collections where account_id matches the authenticated account, parent_id is null, and status='active', ordered by sort_order then created_at.
- get_child_collections returns collections where account_id matches the authenticated account, parent_id is not null, and status='active', ordered by parent_id then sort_order.
- get_collection_by_id must return a collection only if collections.id exists, account_id matches, and status='active'; otherwise return not-found.
- create_collection inserts into collections with account_id, title (required), view defaulting to 'list' if omitted, is_public default false, expanded default false, parent_id optional; parent_id must reference an active collection belonging to the same account.
- update_collection updates only provided fields (title, view, is_public, parent_id, expanded) for an active collection owned by the account; parent_id cannot create cycles (a collection cannot become a descendant of itself).
- delete_collection transitions collections.status from 'active' to 'deleted', sets deleted_at, and moves all raindrops with that collection_id and status='active' to status='trashed' with trashed_at set and collection_id set to null (Trash semantics).
- empty_trash permanently deletes (status='deleted') all raindrops for the account where status='trashed', and cascades raindrop_tags; this operation is idempotent.
- get_raindrop returns a raindrop only if raindrops.id exists, account_id matches, and status in ('active','trashed'); 'deleted' is never returned.
- get_raindrops interprets collection_id parameter as: 0 => all raindrops with status='active'; -1 => collection_id is null and status='active'; -99 => status='trashed'; otherwise => raindrops.collection_id=that id and status='active'.
- get_raindrops supports optional full-text search over (title, excerpt, link, domain, tag names) restricted to the selected collection scope; if search is empty/omitted, no search filter is applied.
- get_raindrops enforces perpage in [1,50] and page >= 0; ordering supports: -created/created => created_at desc/asc; title/-title => title asc/desc; domain/-domain => domain asc/desc; -sort => order asc then created_at desc; score => only valid when search is provided (order by text relevance desc).
- get_tags returns distinct tags for the account; if collection_id provided, it only counts tags attached to raindrops within that collection scope (same scope semantics as get_raindrops except -99 returns tags for trashed raindrops only).
- update_raindrop updates only provided fields for an owned raindrop with status in ('active','trashed'); setting collection_id moves the raindrop (collection_id may be null for unsorted); moving to a collection must reference an active collection in the same account.
- update_raindrop tags parameter replaces the tag set: it upserts tags by (account_id, name_normalized), then sets raindrop_tags to exactly that set; if tags omitted, existing tags remain unchanged.
- update_raindrop important toggles the important boolean; cover sets cover_url; type must be one of the allowed enum values; order must be >= 0 when provided.
- update_many_raindrops requires collection_id scope to select candidate raindrops (same scope semantics as get_raindrops); if ids provided, it restricts to those ids within that scope; it can (a) set important to true/false, (b) set cover_url (if '<screenshot>' then a background job would populate cover_url; here stored as null with a separate internal process), (c) replace tags when tags is an empty list (remove all) or a non-empty list (set exactly), and/or (d) move raindrops to target_collection_id (must be an active collection owned by the account, or null for unsorted).
- All read/write operations are scoped by account_id; cross-account foreign keys are rejected even if ids exist.
- A collection in status='deleted' cannot be assigned as parent_id for another collection and cannot receive raindrops (must be active).