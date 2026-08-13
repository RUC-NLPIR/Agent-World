# Spotify Server — local MCP environment

This backend powers an MCP wrapper around the Spotify Web API. It stores the server's Spotify OAuth tokens, local mirrors of Spotify catalog objects (artists/albums/tracks/audiobooks/playlists), and an audit log of API calls to enforce quotas and support troubleshooting.

Repository: https://github.com/superseoworld/mcp-spotify
Homepage: https://smithery.ai/server/@superseoworld/mcp-spotify

## Datastore

- `oauth_tokens.json` — Stores Spotify OAuth tokens and their lifecycle for the server (client-credentials) and optionally per end-user sessions. Used by get_access_token and to authorize all other tools. (18 rows; fields: ['id', 'token_type', 'access_token', 'refresh_token', 'scope', 'expires_at', 'subject_type', 'spotify_user_id', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'revoked']
  - constraint: expires_at > created_at
  - constraint: subject_type = 'spotify_user' implies spotify_user_id is not null
  - constraint: unique(subject_type, spotify_user_id, status) where status = 'active' (at most one active token per subject)
  - constraint: token_type must be 'Bearer'
- `catalog_items.json` — Local cache/mirror of Spotify catalog entities to serve get_artist/get_album/get_track/get_audiobook/get_playlist and list endpoints without repeatedly refetching. Also stores lightweight fields required for search and recommendations responses. (19 rows; fields: ['id', 'spotify_id', 'entity_type', 'uri', 'href', 'name', 'description_text', 'is_public', 'owner_spotify_user_id', 'release_date', 'duration_ms', 'popularity', 'explicit', 'languages', 'genres', 'images', 'external_urls', 'raw_json', 'cache_status', 'cached_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `cache_status`: ['fresh', 'stale', 'evicted']
  - constraint: unique(entity_type, spotify_id)
  - constraint: popularity between 0 and 100 when popularity is not null
  - constraint: duration_ms >= 0 when duration_ms is not null
  - constraint: entity_type = 'playlist' implies is_public is not null
- `catalog_links.json` — Relationship/join table for Spotify catalog: artist-album, album-track, artist-track (for top tracks), artist-related-artist, audiobook-chapter, category-playlist, and featured playlists snapshots. Enables list endpoints like get_album_tracks, get_artist_albums, get_playlist_items, get_audiobook_chapters, get_category_playlists. (18 rows; fields: ['id', 'link_type', 'from_catalog_item_id', 'to_catalog_item_id', 'position', 'added_at', 'added_by_spotify_user_id', 'snapshot_id', 'market', 'metadata', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: from_catalog_item_id != to_catalog_item_id
  - constraint: position >= 0 when position is not null
  - constraint: unique(link_type, from_catalog_item_id, to_catalog_item_id, market) where status='active'
  - constraint: link_type='playlist_item' implies snapshot_id is not null
- `recommendation_requests.json` — Stores recommendation requests and resolved results from Spotify recommendations endpoint, including seeds (tracks/artists/genres) and the resulting track list. Serves get_recommendations and supports caching/deduplication. (22 rows; fields: ['id', 'seed_tracks_spotify_ids', 'seed_artists_spotify_ids', 'seed_genres', 'market', 'limit', 'tunable_attributes', 'result_track_catalog_item_ids', 'response_raw_json', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['completed', 'failed']
  - constraint: limit between 1 and 100
  - constraint: at least one of seed_tracks_spotify_ids, seed_artists_spotify_ids, seed_genres must be non-empty
  - constraint: no more than 5 total seed items across tracks+artists+genres (Spotify constraint)
  - constraint: status='failed' implies error_message is not null
- `api_requests.json` — Audit log of tool invocations and outbound Spotify requests. Used for rate limiting, debugging, and observing usage by tool (search, get_album_tracks, modify_playlist, etc.). (19 rows; fields: ['id', 'tool_name', 'oauth_token_id', 'spotify_endpoint', 'http_method', 'request_params', 'response_status_code', 'response_time_ms', 'result_cache_hit', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['succeeded', 'failed']
  - constraint: response_time_ms >= 0 when response_time_ms is not null
  - constraint: response_status_code between 100 and 599 when response_status_code is not null
  - constraint: status='failed' implies error_message is not null
  - constraint: FK(oauth_token_id) -> oauth_tokens.id on delete set null

## Business rules enforced by the tools

- get_access_token must create or refresh exactly one oauth_tokens row with subject_type='server' and status='active'; any previously-active server token must transition to expired when its expires_at is in the past.
- All tools except get_access_token must refuse to call Spotify if there is no active oauth_tokens row suitable for the subject (server for public catalog endpoints; spotify_user for user playlist endpoints).
- Catalog reads (get_artist/get_album/get_track/get_audiobook/get_playlist and the corresponding multiple/list endpoints) must first check catalog_items for (entity_type, spotify_id) with cache_status='fresh' and expires_at > now; if present, serve from cache and log api_requests.result_cache_hit=true.
- When a Spotify fetch succeeds for any catalog object, catalog_items must be upserted on unique(entity_type, spotify_id), setting cached_at=now, expires_at=now+TTL, cache_status='fresh', and raw_json to the latest payload.
- Relationship/list endpoints must maintain catalog_links rows for the relevant link_type and from_catalog_item_id; refreshing a list must mark missing prior active rows as status='deleted' and upsert current rows as status='active' with correct position ordering.
- modify_playlist/add_tracks_to_playlist/remove_tracks_from_playlist must only operate on catalog_items.entity_type='playlist'; after a successful modification, all catalog_links with link_type='playlist_item' for that playlist must be marked stale via status='deleted' or refetched, and the new snapshot_id must be recorded on affected catalog_links rows.
- get_artist_top_tracks must store results as catalog_links link_type='artist_top_track' with market populated; uniqueness must include market to allow per-territory variants.
- get_new_releases must store returned albums as catalog_links link_type='new_release_album' from a synthetic catalog_items row with entity_type='category' and spotify_id='new_releases' (or equivalent) to allow consistent linking.
- get_featured_playlists must store returned playlists as catalog_links link_type='featured_playlist' from a synthetic catalog_items row with entity_type='category' and spotify_id='featured' (or equivalent).
- get_category_playlists must require that the category exists as a catalog_items row with entity_type='category' and the requested spotify_id; returned playlists are stored via catalog_links link_type='category_playlist'.
- get_recommendations must enforce Spotify seed constraints: at least 1 seed and at most 5 combined seed tracks+artists+genres; it must persist a recommendation_requests row and set status=completed with response_raw_json on success or status=failed with error_message on failure.
- api_requests must be written for every tool invocation, capturing tool_name, request_params, and status; if an outbound Spotify call is made, spotify_endpoint/http_method/response_status_code/response_time_ms must be populated.
- Cache eviction: a background job may set catalog_items.cache_status='evicted' for items not referenced by any active catalog_links and not accessed for N days; evicted items may be rehydrated on demand.