# YouTube Data Server — local MCP environment

This backend caches YouTube entities (videos, channels) plus time-series statistics snapshots and derived analytics so the service can answer search, trending, related, transcript, and comparison tools efficiently without hitting YouTube on every request. The main workflow is: record a request, fetch/refresh the relevant YouTube resources, store normalized entities + metric snapshots, and serve responses from the cache while enforcing API-key quotas and freshness rules.

Repository: https://github.com/geobio/youtube-data-mcp-server
Homepage: https://smithery.ai/server/@geobio/youtube-data-mcp-server

## Datastore

- `api_keys.json` — Client API keys used to authenticate requests to the server and enforce quota/rate limits. Keys are associated with a logical owner and can be rotated or revoked. (30 rows; fields: ['id', 'key_hash', 'label', 'owner_type', 'owner_id', 'status', 'daily_quota_units', 'per_minute_request_limit', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: daily_quota_units >= 0
  - constraint: per_minute_request_limit >= 0
- `request_logs.json` — Immutable log of tool invocations for auditing, debugging, and quota accounting. Stores the normalized 'tool' name, the resolved inputs, and the cache/fetch outcomes. (33 rows; fields: ['id', 'api_key_id', 'tool_name', 'input', 'status', 'youtube_quota_units_charged', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'served_from_cache', 'fetched_from_youtube', 'failed', 'rate_limited']
  - constraint: youtube_quota_units_charged >= 0
- `channels.json` — Canonical channel records plus periodically refreshed statistics fields used by channel statistics and top-videos queries. (32 rows; fields: ['id', 'youtube_channel_id', 'title', 'description', 'custom_url', 'country', 'published_at', 'status', 'last_refreshed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'unavailable', 'deleted']
  - constraint: unique(youtube_channel_id)
- `videos.json` — Canonical video records including metadata used for details, search results, related videos, trending lists, and channel top videos. (35 rows; fields: ['id', 'youtube_video_id', 'channel_id', 'youtube_channel_id', 'title', 'description', 'published_at', 'duration_seconds', 'default_language', 'category_id', 'region_restriction', 'status', 'last_refreshed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'unavailable', 'deleted']
  - constraint: unique(youtube_video_id)
  - constraint: duration_seconds is null OR duration_seconds >= 0
  - constraint: category_id is null OR category_id >= 0
- `video_metrics.json` — Time-series snapshots of video statistics and derived engagement metrics. Supports engagement ratio, trending/top sorting, and compare videos. (30 rows; fields: ['id', 'video_id', 'snapshot_at', 'view_count', 'like_count', 'comment_count', 'favorite_count', 'engagement_ratio', 'source', 'created_at', 'updated_at'])
  - lifecycle `source`: ['youtube_api', 'computed_from_cache', 'backfill']
  - constraint: unique(video_id, snapshot_at)
  - constraint: view_count is null OR view_count >= 0
  - constraint: like_count is null OR like_count >= 0
  - constraint: comment_count is null OR comment_count >= 0
- `video_transcripts.json` — Cached transcripts/captions per video and language, with optional segmented timing. Supports bulk transcript retrieval. (35 rows; fields: ['id', 'video_id', 'language', 'kind', 'is_generated', 'full_text', 'segments', 'status', 'last_fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'not_found', 'blocked', 'error']
  - constraint: unique(video_id, language, kind)
  - constraint: language <> ''

## Business rules enforced by the tools

- Each tool invocation must create a request_logs row with tool_name set to one of the supported tools and status starting at received, then transitioning to exactly one terminal status (served_from_cache, fetched_from_youtube, failed, rate_limited).
- API keys in status=revoked must not be allowed to create successful (served_from_cache/fetched_from_youtube) request_logs; they can only produce rate_limited or failed.
- Quota enforcement: for a given api_key_id, the sum of youtube_quota_units_charged for request_logs in the current UTC day must not exceed api_keys.daily_quota_units; if it would, the request must be recorded as rate_limited with youtube_quota_units_charged=0.
- Rate limiting: for a given api_key_id, the count of request_logs in the last rolling minute must not exceed api_keys.per_minute_request_limit; if it would, record rate_limited.
- videos.youtube_video_id and channels.youtube_channel_id must be globally unique and treated as the upsert keys when refreshing data from YouTube.
- getVideoDetails must return videos rows (and optionally latest video_metrics) for the requested YouTube video ids; if a video is missing or stale (last_refreshed_at older than the configured freshness window), the service must fetch and refresh the videos row and append a new video_metrics snapshot.
- searchVideos must persist discovered videos (upsert into videos) and may optionally record an associated request_logs.input containing query text; returned items are served from videos with metadata populated.
- getRelatedVideos must upsert the seed video and the related videos into videos; the response ordering is derived from YouTube recommendation order but served from the cached video rows.
- getTrendingVideos must filter/sort by region/category at request time; the backend stores category_id and can store region restrictions per video. Trending ordering should be based on the newest available video_metrics snapshot when available; otherwise fall back to metadata recency.
- getChannelStatistics must upsert channels and refresh last_refreshed_at; statistics are returned from the most recent fetched state (either stored in channels metadata or derived from associated videos/video_metrics as needed by the implementation).
- getChannelTopVideos must return videos belonging to the channel sorted by latest video_metrics.view_count descending; if video_metrics are absent, return based on best-effort (e.g., skip or fetch).
- getTranscripts must upsert videos first (if unknown) then upsert video_transcripts by (video_id, language, kind); if transcript fetch fails, set status to error with last_fetched_at updated.
- getVideoEngagementRatio and compareVideos must read the latest video_metrics snapshot per video_id; if no snapshot exists or is stale, the service must fetch current statistics and append a new snapshot before computing engagement_ratio.