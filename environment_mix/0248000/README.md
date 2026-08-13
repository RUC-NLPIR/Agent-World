# YouTube Toolbox — local MCP environment

This backend stores cached YouTube entities (channels, videos, comments, transcripts) and the history of user/tool fetches and searches so the service can serve repeated requests quickly, enforce quotas, and track lifecycle/status of ingestions. Main workflows: users/API clients perform searches or request details/comments/transcripts; the system fetches from YouTube when not cached or stale, stores normalized results, and returns materialized views.

Repository: https://github.com/jikime/py-mcp-youtube-toolbox
Homepage: https://smithery.ai/server/@jikime/py-mcp-youtube-toolbox

## Datastore

- `api_clients.json` — API clients/workspaces using the YouTube Toolbox service. Used for authentication, quota enforcement, and request auditing across all tools. (34 rows; fields: ['id', 'name', 'api_key_hash', 'status', 'quota_daily_requests', 'quota_daily_youtube_units', 'quota_reset_at', 'requests_used_today', 'youtube_units_used_today', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(api_key_hash)
  - constraint: quota_daily_requests >= 0
  - constraint: quota_daily_youtube_units >= 0
  - constraint: requests_used_today >= 0
- `channels.json` — Cached YouTube channel metadata returned by get_channel_details and used to decorate video results. (33 rows; fields: ['id', 'youtube_channel_id', 'handle', 'title', 'description', 'country', 'published_at', 'thumbnails', 'stats', 'last_fetched_at', 'etag', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'tombstoned']
  - constraint: unique(youtube_channel_id)
  - constraint: country is null OR length(country) = 2
- `videos.json` — Cached YouTube video metadata used by search_videos, get_video_details, get_related_videos, and get_trending_videos. (34 rows; fields: ['id', 'youtube_video_id', 'channel_id', 'title', 'description', 'published_at', 'duration_seconds', 'category_id', 'default_language', 'tags', 'thumbnails', 'stats', 'region_restriction', 'last_fetched_at', 'etag', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'unavailable', 'tombstoned']
  - constraint: unique(youtube_video_id)
  - constraint: duration_seconds is null OR duration_seconds >= 0
- `video_text_assets.json` — Stores video transcripts/captions and comments. Supports get_video_transcript, get_video_enhanced_transcript, and get_video_comments. Designed as a polymorphic text-asset store to stay within collection limits while modeling real entities. (34 rows; fields: ['id', 'video_id', 'asset_type', 'youtube_asset_id', 'language', 'is_auto_generated', 'author_channel_youtube_id', 'author_display_name', 'like_count', 'published_at', 'segments', 'text', 'source', 'last_fetched_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'stale', 'unavailable', 'tombstoned']
  - constraint: like_count is null OR like_count >= 0
  - constraint: segments is null OR asset_type = 'transcript'
  - constraint: text is null OR length(text) <= 200000
  - constraint: unique(video_id, asset_type, youtube_asset_id)
- `tool_requests.json` — Audit and caching layer for all tool calls. Stores inputs/outputs, links to involved entities, and supports replay/debugging plus quota accounting for every endpoint in the tool surface. (38 rows; fields: ['id', 'client_id', 'tool_name', 'input_params', 'normalized_query', 'region_code', 'youtube_video_id', 'youtube_channel_id', 'resolved_video_id', 'resolved_channel_id', 'response_payload', 'http_status', 'error_code', 'error_message', 'youtube_units_charged', 'cache_hit', 'status', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: youtube_units_charged >= 0
  - constraint: http_status is null OR (http_status >= 100 AND http_status <= 599)
  - constraint: region_code is null OR length(region_code) = 2
  - constraint: finished_at is null OR started_at is not null

## Business rules enforced by the tools

- Every tool invocation must create a tool_requests row with status=received, then transition to running, then to exactly one terminal state (succeeded|failed|cancelled).
- Requests for video-targeted tools must include a youtube_video_id; requests for channel-targeted tools must include a youtube_channel_id; violating requests must be recorded as failed with http_status=400.
- For each api_clients row with status!=active, all incoming tool invocations must be rejected and logged as failed with error_code='CLIENT_INACTIVE'.
- Before executing any tool, if quota_reset_at <= now then requests_used_today and youtube_units_used_today must be reset to 0 and quota_reset_at advanced to the next reset boundary.
- A tool invocation must be rejected (and logged) if requests_used_today + 1 > quota_daily_requests or youtube_units_used_today + youtube_units_charged > quota_daily_youtube_units.
- videos.youtube_video_id and channels.youtube_channel_id must be globally unique; inserts must upsert/update last_fetched_at and set status to active unless upstream indicates unavailability.
- If an upstream fetch indicates a removed/private video or channel, set videos.status or channels.status to unavailable/tombstoned and do not serve stale cached metadata unless explicitly allowed by policy.
- get_video_transcript and get_video_enhanced_transcript must read transcript assets from video_text_assets where asset_type='transcript' and status in ('available','stale'); if none exists or status='unavailable', the system must attempt re-extraction and update last_fetched_at/status accordingly.
- get_video_comments must read comment assets from video_text_assets where asset_type='comment'; repeated fetches should upsert by unique(video_id, asset_type, youtube_asset_id) to avoid duplicates.
- get_video_enhanced_transcript must implement its filtering/search/segmentation over video_text_assets.segments (time range filtering by start_ms/end_ms, search by segment text, segmentation by time or count) and may optionally embed videos/channels metadata from videos/channels when include metadata is requested.