# YouTube Data API Server — local MCP environment

This backend models a YouTube Data API proxy/server that manages authenticated creator accounts, caches YouTube entities (channels, videos, playlists), and records API operations (search, reads, uploads, updates) with quota/cost tracking. Main workflows include: users connect a Google/YouTube channel via OAuth, perform searches and entity lookups, upload/update videos, and create/list playlists while the server enforces quotas and stores operation logs and cached results.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@midwest/yt-data-v3-mcp

## Datastore

- `accounts.json` — Represents a connected Google/YouTube account (OAuth identity) used to call YouTube Data API on behalf of a user/channel. Stores encrypted tokens, channel ownership, and account lifecycle. (18 rows; fields: ['id', 'provider', 'google_subject', 'default_channel_id', 'scopes', 'access_token_ciphertext', 'refresh_token_ciphertext', 'token_expires_at', 'quota_daily_limit_units', 'quota_daily_used_units', 'quota_reset_at', 'status', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked', 'suspended']
  - constraint: unique(provider, google_subject)
  - constraint: quota_daily_limit_units >= 0
  - constraint: quota_daily_used_units >= 0
  - constraint: quota_daily_used_units <= quota_daily_limit_units OR quota_daily_limit_units = 0 (0 means unlimited for internal/admin)
- `channels.json` — Cached YouTube channel metadata referenced by searches and operations. May be updated on reads (get_channel_info) and used as ownership for uploads/playlist creation. (18 rows; fields: ['id', 'youtube_channel_id', 'title', 'description', 'custom_url', 'published_at', 'country', 'subscriber_count', 'video_count', 'view_count', 'etag', 'fetched_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'unknown']
  - constraint: unique(youtube_channel_id)
  - constraint: subscriber_count IS NULL OR subscriber_count >= 0
  - constraint: video_count IS NULL OR video_count >= 0
  - constraint: view_count IS NULL OR view_count >= 0
- `videos.json` — Cached YouTube video metadata, including privacy and publication state, used for details, channel listings, and unpublished video queries. Also stores last-known metadata for uploaded/updated videos. (19 rows; fields: ['id', 'youtube_video_id', 'channel_id', 'title', 'description', 'tags', 'category_id', 'default_language', 'privacy_status', 'upload_status', 'publish_at', 'published_at', 'duration_seconds', 'view_count', 'like_count', 'comment_count', 'thumbnails', 'etag', 'fetched_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'unknown']
  - constraint: unique(youtube_video_id)
  - constraint: fk(channel_id) references channels.id on update cascade on delete restrict
  - constraint: duration_seconds IS NULL OR duration_seconds >= 0
  - constraint: view_count IS NULL OR view_count >= 0
- `playlists.json` — Cached YouTube playlists and their metadata. Used for listing playlists and creating new playlists; items may be fetched separately by the API server if needed. (18 rows; fields: ['id', 'youtube_playlist_id', 'channel_id', 'title', 'description', 'privacy_status', 'item_count', 'published_at', 'etag', 'fetched_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted', 'unknown']
  - constraint: unique(youtube_playlist_id)
  - constraint: fk(channel_id) references channels.id on update cascade on delete restrict
  - constraint: item_count IS NULL OR item_count >= 0
  - constraint: privacy_status IN ('public','private','unlisted')
- `api_operations.json` — Append-only log of all tool invocations and their interaction with YouTube Data API, including request/response payloads (sanitized), pagination tokens, errors, and server-side quota accounting. This is the operational backbone enabling every tool to be audited and rate-limited. (20 rows; fields: ['id', 'account_id', 'tool_name', 'youtube_endpoint', 'request_params', 'request_body', 'response_body', 'http_status', 'error_code', 'error_message', 'quota_units_charged', 'latency_ms', 'page_token_in', 'page_token_out', 'result_video_ids', 'result_channel_ids', 'result_playlist_ids', 'status', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(account_id) references accounts.id on update cascade on delete set null
  - constraint: quota_units_charged >= 0
  - constraint: latency_ms IS NULL OR latency_ms >= 0
  - constraint: http_status IS NULL OR (http_status >= 100 AND http_status <= 599)

## Business rules enforced by the tools

- All tool invocations MUST create an api_operations row with tool_name matching the invoked tool and status transitioning queued -> running -> (succeeded|failed|cancelled).
- For authenticated tools (upload_video, update_video, create_playlist, get_unpublished_videos), api_operations.account_id MUST be non-null and the referenced accounts.status MUST be 'active'.
- Before executing an operation, if accounts.quota_daily_limit_units > 0 then (accounts.quota_daily_used_units + api_operations.quota_units_charged) MUST NOT exceed accounts.quota_daily_limit_units; otherwise the operation MUST fail with error_code='quotaExceeded' and status='failed'.
- search_videos results MUST be persisted by upserting any returned channels into channels and any returned videos into videos, and recording their natural IDs in api_operations.result_channel_ids/result_video_ids.
- get_video_details MUST upsert into videos by youtube_video_id and set videos.fetched_at to the call time; if the video is not found, videos.status MUST transition to 'deleted' (or a stub row may be created with status='deleted').
- get_channel_info MUST upsert into channels by youtube_channel_id and set channels.fetched_at to the call time; if not found, channels.status MUST transition to 'deleted' (or a stub row may be created with status='deleted').
- list_channel_videos MUST require a resolvable channel (channels row exists or is created), upsert returned videos with channel_id pointing to that channel, and record pagination tokens in api_operations.page_token_in/page_token_out.
- get_unpublished_videos MUST only return videos with privacy_status IN ('private','unlisted') OR publish_at IS NOT NULL, and MUST be scoped to the authenticated account's default_channel_id (or a channel explicitly associated to that account).
- upload_video MUST create or upsert a videos row with privacy_status and upload_status='uploaded' (or 'processed' if immediately available) and associate it to the authenticated account's channel (videos.channel_id).
- update_video MUST only update videos cached fields (title/description/tags/category_id/privacy_status/publish_at) after a successful YouTube update; privacy_status transitions MUST be limited to ('private'|'unlisted'|'public') and publish_at MUST be null unless scheduling is supported by the server configuration.
- get_playlists MUST upsert playlists by youtube_playlist_id for the requested/derived channel and set playlists.fetched_at; create_playlist MUST insert into playlists after YouTube confirms creation and set privacy_status appropriately.
- The server MUST never store raw OAuth tokens in plaintext; access_token_ciphertext and refresh_token_ciphertext MUST be encrypted-at-rest and excluded from api_operations.request_body/response_body.