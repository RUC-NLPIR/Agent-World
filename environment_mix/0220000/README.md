# YouTube MCP Server — local MCP environment

This backend stores cached YouTube entities (videos, channels) plus derived analytics (engagement ratios, comparisons) and text assets (transcripts). Tools read from these caches and, when missing or stale, the service would fetch from YouTube APIs and upsert the corresponding rows, tracking freshness via timestamps and lightweight lifecycle/status fields.

Repository: https://github.com/icraft2170/youtube-data-mcp-server
Homepage: https://smithery.ai/server/@icraft2170/youtube-data-mcp-server

## Datastore

- `channels.json` — YouTube channels cached from the YouTube Data API, including current statistics and basic metadata used by channel stats and top-videos tools. (19 rows; fields: ['id', 'youtube_channel_id', 'title', 'description', 'custom_url', 'country', 'published_at', 'thumbnail_url', 'subscriber_count', 'view_count', 'video_count', 'stats_captured_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(youtube_channel_id)
  - constraint: subscriber_count is null or subscriber_count >= 0
  - constraint: view_count is null or view_count >= 0
  - constraint: video_count is null or video_count >= 0
- `videos.json` — YouTube videos cached from the YouTube Data API. Supports video details, search results, related videos, trending videos, comparisons, and engagement computations. (19 rows; fields: ['id', 'youtube_video_id', 'channel_id', 'title', 'description', 'published_at', 'duration_seconds', 'category_id', 'default_language', 'thumbnail_url', 'tags', 'is_live_content', 'region_code_last_seen', 'view_count', 'like_count', 'comment_count', 'stats_captured_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'unavailable', 'deleted']
  - constraint: unique(youtube_video_id)
  - constraint: fk(channel_id) references channels(id)
  - constraint: duration_seconds is null or duration_seconds >= 0
  - constraint: category_id is null or category_id in (1,2,10,15,17,18,19,20,21)
- `transcripts.json` — Caption/transcript text assets per video and language. Used by getTranscripts and indirectly by analysis tooling. (18 rows; fields: ['id', 'video_id', 'language', 'is_auto_generated', 'format', 'content_text', 'content_segments', 'source', 'captured_at', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'missing', 'error', 'stale']
  - constraint: fk(video_id) references videos(id)
  - constraint: unique(video_id, language, is_auto_generated, source)
  - constraint: format='plain_text' implies content_text is not null and content_segments is null
  - constraint: format='segments_json' implies content_segments is not null
- `video_relationships.json` — Materialized edges between videos for 'related videos' and for recording trending list membership. Enables deterministic reads and caching of recommendation/trending results over time. (18 rows; fields: ['id', 'source_video_id', 'target_video_id', 'relation_type', 'region_code', 'category_id', 'rank', 'score', 'captured_at', 'expires_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'invalid']
  - constraint: fk(source_video_id) references videos(id)
  - constraint: fk(target_video_id) references videos(id)
  - constraint: relation_type='related' implies source_video_id is not null and region_code is null and category_id is null
  - constraint: relation_type='trending_list' implies source_video_id is null and region_code is not null and category_id is not null
- `tool_requests.json` — Audit and cache-control for MCP tool invocations. Since the published tool schemas show empty parameter objects, this table records the raw request payload, derived lookup keys, and outcomes to support idempotency, debugging, and rate/quota enforcement. (19 rows; fields: ['id', 'tool_name', 'raw_parameters', 'request_key', 'status', 'started_at', 'completed_at', 'error_message', 'result_summary', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed']
  - constraint: unique(request_key)
  - constraint: completed_at is null or started_at is not null
  - constraint: status in ('succeeded','failed') implies completed_at is not null

## Business rules enforced by the tools

- When a tool requires a video id (getVideoDetails, getRelatedVideos, getVideoEngagementRatio, compareVideos), the implementation must resolve it to videos.youtube_video_id and upsert into videos (and channels) if not present or if stats_captured_at is older than the configured TTL.
- getChannelStatistics and getChannelTopVideos must resolve/accept YouTube channel ids and upsert into channels; channel stats refresh updates subscriber_count/view_count/video_count and sets stats_captured_at.
- getTranscripts for a set of videos must upsert transcripts rows keyed by (video_id, language, is_auto_generated, source); if captions are unavailable, set status=missing and do not create content_text/content_segments.
- getRelatedVideos must write video_relationships rows with relation_type='related' for each (source_video_id,target_video_id) captured, and expire prior edges for that source when new edges are captured (set status=expired, expires_at).
- getTrendingVideos must materialize the trending list as video_relationships rows with relation_type='trending_list' and require region_code and category_id; ranks must be consecutive positive integers within a captured_at batch.
- getVideoEngagementRatio must compute engagement_ratio = (like_count + comment_count) / nullif(view_count,0) at read time from videos.*; if view_count is null or 0, ratio must be null and not throw.
- compareVideos must read a consistent snapshot of stats for the requested videos; if multiple are stale beyond TTL, refresh all or mark the comparison as partial in tool_requests.result_summary.
- All tool invocations must create a tool_requests row; retries with identical normalized inputs must reuse the same request_key and return the prior succeeded result when available (idempotent behavior).
- FK integrity must be preserved: videos.channel_id must exist in channels; transcripts.video_id and video_relationships.*_video_id must exist in videos (upsert parent rows before inserting children).