# Advanced YouTube — local MCP environment

This backend stores cached YouTube discovery and analytics data (videos, channels, categories, trending lists) plus transcript assets (caption tracks, caption segments, derived key moments/segmentations) so the API can serve high-volume read endpoints without repeatedly calling upstream sources. Core workflows: ingest/search/trending queries create query runs and result items; video/channel stats are snapshotted over time; transcripts are fetched per video/language and materialized into segments to support enhanced transcript, segmentation, and key-moment extraction.

Repository: https://github.com/coyaSONG/youtube-mcp-server
Homepage: https://smithery.ai/server/@coyaSONG/youtube-mcp-server

## Datastore

- `api_clients.json` — Represents a calling client/application (API key holder). Used for authentication, rate limiting, and usage auditing across all tools. (18 rows; fields: ['id', 'name', 'api_key_hash', 'status', 'daily_request_quota', 'daily_youtube_units_quota', 'created_at', 'updated_at', 'last_used_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(api_key_hash)
  - constraint: unique(name)
  - constraint: daily_request_quota >= 0
  - constraint: daily_youtube_units_quota >= 0
- `channels.json` — Canonical channel records with basic metadata and the latest known statistics. Supports get-channel-stats and as a foreign key for videos. (18 rows; fields: ['id', 'youtube_channel_id', 'title', 'handle', 'country', 'description', 'thumbnail_url', 'status', 'subscriber_count', 'view_count', 'video_count', 'stats_as_of', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'unavailable', 'deleted']
  - constraint: unique(youtube_channel_id)
  - constraint: subscriber_count is null or subscriber_count >= 0
  - constraint: view_count is null or view_count >= 0
  - constraint: video_count is null or video_count >= 0
- `videos.json` — Canonical video records with metadata and latest stats. Serves search-videos, get-video-stats, compare-videos, get-trending-videos, analyze-channel-videos, and as the parent entity for comments and transcripts. (18 rows; fields: ['id', 'youtube_video_id', 'channel_id', 'title', 'description', 'published_at', 'duration_seconds', 'category_id', 'default_language', 'default_audio_language', 'tags', 'thumbnail_url', 'status', 'view_count', 'like_count', 'comment_count', 'stats_as_of', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'restricted', 'unavailable', 'deleted']
  - constraint: unique(youtube_video_id)
  - constraint: duration_seconds is null or duration_seconds >= 0
  - constraint: view_count is null or view_count >= 0
  - constraint: like_count is null or like_count >= 0
- `video_text_assets.json` — Stores text-derived assets for videos: comment snapshots, transcript tracks with segments, and derived analyses (key moments, segmented transcript). This single table supports get-video-comments, get-video-transcript, enhanced-transcript, get-key-moments, and get-segmented-transcript. (20 rows; fields: ['id', 'video_id', 'asset_type', 'language', 'source', 'status', 'version', 'expires_at', 'payload', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'ready', 'failed', 'expired']
  - constraint: foreign key(video_id) references videos(id) on update cascade on delete cascade
  - constraint: version >= 1
  - constraint: language is null or length(language) between 2 and 16
  - constraint: unique(video_id, asset_type, coalesce(language,''), version)
- `query_runs.json` — Audit and caching for all read tools. Each tool invocation creates a query run with normalized inputs and references to resulting entities/assets. Supports search-videos, get-trending-videos, get-video-categories, get-video-stats, get-channel-stats, compare-videos, analyze-channel-videos, and transcript/comment tools with optional caching and deduplication. (21 rows; fields: ['id', 'client_id', 'tool_name', 'status', 'request_fingerprint', 'parameters', 'response_ref', 'youtube_units_used', 'cache_hit', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(client_id) references api_clients(id) on update cascade on delete restrict
  - constraint: youtube_units_used >= 0
  - constraint: unique(client_id, tool_name, request_fingerprint) where status in ('succeeded') and finished_at > now() - interval '24 hours'

## Business rules enforced by the tools

- Every tool invocation must create a query_runs row; status must transition queued -> running -> (succeeded|failed|cancelled) with started_at set on running and finished_at set on terminal states.
- api_clients.status must be active to execute any tool; suspended or revoked clients must be denied and a failed query_runs record must be written with error_message='client_not_active'.
- For quota enforcement: a client may not exceed daily_request_quota requests/day nor daily_youtube_units_quota upstream units/day; if exceeded, the request must not call upstream sources and must write query_runs.status='failed' with error_message indicating which quota was exceeded.
- videos.youtube_video_id and channels.youtube_channel_id must be globally unique; repeated discovery must upsert metadata and refresh stats_as_of without creating duplicates.
- get-video-stats and compare-videos must read from videos.* counts; if stats_as_of is older than a configured TTL (e.g., 6 hours), the implementation should refresh counts and update stats_as_of (or record status=unavailable if upstream cannot provide).
- get-channel-stats must read from channels.* counts; if stats_as_of is older than TTL, refresh and update stats_as_of.
- get-video-transcript must return the latest ready video_text_assets row where asset_type='transcript_track' and language matches requested language (or default_language fallback), preferring the highest version; if none exists or it is expired, enqueue a new asset (status=queued) and then attempt to materialize it to ready.
- enhanced-transcript must be able to: (a) fetch multiple videos by producing multiple transcript_track assets; (b) filter by time ranges and search terms by operating over payload.captions timestamps/text; and (c) segment by producing a derived segmented_transcript asset (asset_type='segmented_transcript', source='derived', status='ready').
- get-segmented-transcript must create or reuse a segmented_transcript asset keyed by (video_id, language, segmentCount in query_runs.parameters); if segmentCount is omitted, use a service default and record it in query_runs.parameters.normalized.
- get-key-moments must create or reuse a key_moments asset keyed by (video_id, language, maxMoments in query_runs.parameters); maxMoments must be within [1, 50] (service-enforced) and stored in parameters.normalized.
- get-video-comments must create or reuse a comments_snapshot asset; when upstream pagination is used, nextPageToken must be stored in payload and the snapshot version incremented on subsequent fetches.
- get-trending-videos and get-video-categories must be cacheable via query_runs.request_fingerprint including normalized region/category inputs (even if not exposed in published schema); the response_ref must point to the involved video ids and/or embedded category data.