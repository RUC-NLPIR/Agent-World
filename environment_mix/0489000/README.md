# YouTube Insights — local MCP environment

This backend powers a YouTube research/insights API that lets clients (via API keys) search YouTube videos, fetch channel info (plus recent videos), and retrieve/cached transcripts for videos. It stores normalized YouTube entities (channels, videos, transcripts) and logs each tool invocation as a request for auditing, throttling, and caching.

Repository: https://github.com/dabidstudio/youtubeinsights-mcp-server
Homepage: https://smithery.ai/server/@dabidstudio/youtubeinsights-mcp-server

## Datastore

- `api_keys.json` — API keys used by clients to access the service, including status, simple quotas, and audit metadata. (19 rows; fields: ['id', 'key_hash', 'label', 'status', 'daily_request_limit', 'daily_request_count', 'daily_window_start_at', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(key_hash)
  - constraint: daily_request_limit >= 0
  - constraint: daily_request_count >= 0
  - constraint: daily_request_count <= daily_request_limit OR daily_request_limit = 0 (0 means unlimited)
- `channels.json` — Normalized YouTube channel records resolved during channel-info lookups and from video search results. (18 rows; fields: ['id', 'youtube_channel_id', 'handle', 'title', 'description', 'country', 'subscriber_count', 'video_count', 'view_count', 'thumbnail_url', 'fetched_at', 'created_at', 'updated_at'])
  - constraint: unique(youtube_channel_id)
  - constraint: subscriber_count IS NULL OR subscriber_count >= 0
  - constraint: video_count IS NULL OR video_count >= 0
  - constraint: view_count IS NULL OR view_count >= 0
- `videos.json` — Normalized YouTube video records sourced from searches, channel recent-video lists, and transcript retrieval requests. (18 rows; fields: ['id', 'youtube_video_id', 'channel_id', 'title', 'description', 'published_at', 'duration_seconds', 'view_count', 'like_count', 'comment_count', 'thumbnail_url', 'language', 'fetched_at', 'created_at', 'updated_at'])
  - constraint: unique(youtube_video_id)
  - constraint: duration_seconds IS NULL OR duration_seconds >= 0
  - constraint: view_count IS NULL OR view_count >= 0
  - constraint: like_count IS NULL OR like_count >= 0
- `transcripts.json` — Cached transcripts for YouTube videos, including fetch lifecycle and optional segmentation payload. (18 rows; fields: ['id', 'video_id', 'language', 'is_auto_generated', 'status', 'transcript_text', 'segments', 'source', 'error_code', 'error_message', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'unavailable', 'fetching', 'error']
  - constraint: video_id references videos.id
  - constraint: unique(video_id, language, is_auto_generated, source)
  - constraint: is_auto_generated IN (true,false)
  - constraint: status IN ('available','unavailable','fetching','error')
- `tool_requests.json` — Audit log of each MCP tool invocation, including inputs, resolution targets (video/channel), and outputs for reproducibility and caching. (20 rows; fields: ['id', 'api_key_id', 'tool_name', 'status', 'input', 'resolved_youtube_video_id', 'resolved_youtube_channel_id', 'video_id', 'channel_id', 'output', 'error_message', 'upstream_provider', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: api_key_id references api_keys.id
  - constraint: tool_name IN ('search_youtube_videos','get_channel_info','get_youtube_transcript')
  - constraint: status IN ('queued','running','succeeded','failed')
  - constraint: finished_at IS NULL OR started_at IS NOT NULL

## Business rules enforced by the tools

- Every tool invocation must create a tool_requests row with tool_name matching the invoked tool and input capturing the received JSON (even if empty).
- Requests must be rejected if the caller api_key.status != 'active'.
- On each accepted tool invocation, api_keys.daily_request_count must increment by 1 within the correct UTC window; if daily_request_limit > 0 and daily_request_count would exceed it, the request must be rejected.
- search_youtube_videos must upsert videos (by youtube_video_id) and channels (by youtube_channel_id) for returned results when identifiers are present, and may store the raw response JSON in tool_requests.output.
- get_channel_info must resolve a youtube_channel_id from the provided video URL (or fail); it must upsert the channel and upsert up to 10 recent videos, linking videos.channel_id to channels.id.
- get_youtube_transcript must resolve a youtube_video_id (directly or extracted from a URL); it must upsert the video, then upsert a transcript row keyed by (video_id, language, is_auto_generated, source). If a cached transcript is status='available' and not stale per internal TTL, the tool should return it without refetching.
- transcripts.status transitions must follow the declared lifecycle; in particular, a transcript can only move to available/unavailable/error from fetching, and retries set status back to fetching.
- FK integrity: videos.channel_id must reference an existing channels row when not null; transcripts.video_id must reference an existing videos row; tool_requests.*_id FKs must reference existing rows when not null.
- Uniqueness: youtube_channel_id and youtube_video_id must be globally unique in their respective collections; transcripts must be unique per (video_id, language, is_auto_generated, source).