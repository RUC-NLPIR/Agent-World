# YouTube Data Interaction Server — local MCP environment

This backend stores cached YouTube metadata (videos, channels, comments, categories, transcripts) and an auditable history of user tool calls. Core workflows: execute read-only tools against YouTube, normalize/store results for reuse, and persist derived artifacts like segmented transcripts and extracted key moments for faster repeated access.

Repository: https://github.com/xianxx17/my-youtube-mcp-server
Homepage: https://smithery.ai/server/@xianxx17/my-youtube-mcp-server

## Datastore

- `api_requests.json` — Audit log of every tool invocation (search, stats, transcript, trending, analysis) including normalized parameters and response metadata for caching, debugging, and quota enforcement. (37 rows; fields: ['id', 'tool_name', 'status', 'request_params', 'request_fingerprint', 'cache_mode', 'cache_hit', 'response_summary', 'error_code', 'error_message', 'youtube_quota_cost', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: unique(request_fingerprint) WHERE status IN ('succeeded') AND finished_at IS NOT NULL
  - constraint: youtube_quota_cost >= 0
  - constraint: finished_at IS NULL OR started_at IS NOT NULL
  - constraint: finished_at IS NULL OR finished_at >= started_at
- `channels.json` — Normalized YouTube channel entities and periodically refreshed channel-level stats used by get-channel-stats and analyze-channel-videos. (20 rows; fields: ['id', 'youtube_channel_id', 'title', 'handle', 'country', 'description', 'thumbnail_url', 'subscriber_count', 'view_count', 'video_count', 'stats_fetched_at', 'created_at', 'updated_at'])
  - constraint: unique(youtube_channel_id)
  - constraint: subscriber_count IS NULL OR subscriber_count >= 0
  - constraint: view_count IS NULL OR view_count >= 0
  - constraint: video_count IS NULL OR video_count >= 0
- `videos.json` — YouTube videos with searchable metadata, statistics, and links to channel and category. Supports search, stats, trending, and channel video analysis. (36 rows; fields: ['id', 'youtube_video_id', 'channel_id', 'title', 'description', 'published_at', 'duration_seconds', 'default_language', 'region_code', 'category_id', 'thumbnail_url', 'view_count', 'like_count', 'comment_count', 'stats_fetched_at', 'trending_rank', 'trending_fetched_at', 'created_at', 'updated_at'])
  - constraint: unique(youtube_video_id)
  - constraint: duration_seconds IS NULL OR duration_seconds >= 0
  - constraint: view_count IS NULL OR view_count >= 0
  - constraint: like_count IS NULL OR like_count >= 0
- `video_categories.json` — YouTube video categories by region used by get-video-categories and for annotating videos in trending/search results. (25 rows; fields: ['id', 'region_code', 'youtube_category_id', 'title', 'assignable', 'fetched_at', 'created_at', 'updated_at'])
  - constraint: unique(region_code, youtube_category_id)
- `video_text_assets.json` — Stores comments and transcript/caption assets, plus derived artifacts like segmented transcripts and key moments. Serves get-video-comments, get-video-transcript, enhanced-transcript, get-key-moments, and get-segmented-transcript. (34 rows; fields: ['id', 'video_id', 'asset_type', 'status', 'language', 'sort_order', 'youtube_comment_id', 'parent_youtube_comment_id', 'author_channel_id', 'published_at', 'like_count', 'text', 'start_ms', 'duration_ms', 'payload', 'source_request_id', 'derived_from_asset_id', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'ready', 'stale', 'error']
  - constraint: like_count IS NULL OR like_count >= 0
  - constraint: start_ms IS NULL OR start_ms >= 0
  - constraint: duration_ms IS NULL OR duration_ms >= 0
  - constraint: unique(video_id, asset_type, language) WHERE asset_type IN ('transcript_full','transcript_segmented','key_moments')

## Business rules enforced by the tools

- Every tool call must create exactly one api_requests row; status must reach one terminal state (succeeded|failed|cancelled) with finished_at set.
- search-videos must upsert channels and videos by youtube_channel_id/youtube_video_id and record the serving api_requests row (cache_hit may be true).
- get-video-stats must refresh videos.view_count/like_count/comment_count and stats_fetched_at for the requested youtube_video_id (creating the video if missing after resolving its channel).
- get-channel-stats must refresh channels.subscriber_count/view_count/video_count and stats_fetched_at for the requested youtube_channel_id.
- compare-videos must read stats from videos for each requested youtube_video_id; if any are missing or stale, it may refresh them and must attribute any refresh to the api_requests row's youtube_quota_cost.
- get-trending-videos must upsert videos observed in trending and set region_code, trending_rank, trending_fetched_at; if category is known it must reference video_categories.id for that region.
- get-video-categories must upsert video_categories for the requested region_code, enforcing unique(region_code, youtube_category_id).
- get-video-comments must store comment_thread/comment assets in video_text_assets with sort_order recorded and youtube_comment_id uniqueness enforced per video.
- get-video-transcript must store a transcript_full asset for (video_id, language) (or default language if unspecified) with payload containing the timestamped captions; repeated calls should return cached asset when status=ready and fetched_at is recent enough.
- enhanced-transcript may accept multiple videos and must create transcript_full assets per (video_id, language) as needed; time-range filtering, search, and segmentation are computed from stored caption payloads and may be persisted as transcript_segmented assets when requested.
- get-key-moments must derive a key_moments asset from an existing transcript_full asset (derived_from_asset_id set) and must not exceed a server-side maxMoments limit (e.g., 100).
- get-segmented-transcript must derive a transcript_segmented asset from transcript_full with a server-side segmentCount range (e.g., 2..200) and must store the segmentation parameters inside payload for reproducibility.