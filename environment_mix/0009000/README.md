# YouTube Transcript Server — local MCP environment

This backend stores YouTube video metadata and extracted transcripts per language, plus a job log of transcript extraction requests. The main workflow is: accept a get_transcripts request (url/id + optional lang + formatting option), normalize/resolve the video id, fetch and store transcript segments, and return a formatted transcript (optionally with paragraph breaks).

Repository: https://github.com/sinco-lab/mcp-youtube-transcript
Homepage: https://smithery.ai/server/@sinco-lab/mcp-youtube-transcript

## Datastore

- `videos.json` — Normalized YouTube video records resolved from user-provided URLs or IDs. Used to de-duplicate transcript storage across repeated requests. (17 rows; fields: ['id', 'youtube_video_id', 'canonical_url', 'title', 'channel_id', 'duration_seconds', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'unavailable', 'deleted']
  - constraint: unique(youtube_video_id)
  - constraint: youtube_video_id length between 6 and 20 (to tolerate shorts/live ids while still validating) and matches /^[A-Za-z0-9_-]+$/
  - constraint: canonical_url like 'https://www.youtube.com/watch?v=%'
- `transcript_tracks.json` — A transcript track for a specific video and language code. Stores the raw upstream transcript payload and a normalized summary for fast responses. (18 rows; fields: ['id', 'video_id', 'lang', 'is_auto_generated', 'source', 'raw_payload', 'segment_count', 'text_plain', 'status', 'last_fetched_at', 'failure_reason', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'fetching', 'failed', 'unavailable']
  - constraint: unique(video_id, lang)
  - constraint: segment_count >= 0
  - constraint: lang length between 2 and 12
  - constraint: FK(video_id) references videos(id) on delete cascade
- `transcript_segments.json` — Normalized transcript segments for a transcript track, preserving timing information for reconstruction and formatting (e.g., paragraph breaks). (18 rows; fields: ['id', 'track_id', 'seq', 'start_ms', 'duration_ms', 'end_ms', 'text', 'created_at', 'updated_at'])
  - constraint: unique(track_id, seq)
  - constraint: start_ms >= 0
  - constraint: duration_ms >= 0
  - constraint: end_ms = start_ms + duration_ms (computed or checked constraint)
- `transcript_requests.json` — Request log and idempotency store for get_transcripts calls, including the requested language and formatting options. Used for rate limiting, debugging, and caching behavior. (19 rows; fields: ['id', 'request_key', 'input_url', 'normalized_video_id', 'video_id', 'lang', 'enable_paragraphs', 'response_text', 'track_id', 'status', 'error_code', 'error_message', 'processing_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'processing', 'succeeded', 'failed']
  - constraint: unique(request_key)
  - constraint: lang length between 2 and 12
  - constraint: processing_ms is null or processing_ms >= 0
  - constraint: FK(video_id) references videos(id) on delete set null

## Business rules enforced by the tools

- get_transcripts.url must be stored verbatim in transcript_requests.input_url, and parsing must attempt to derive transcript_requests.normalized_video_id; if parsing fails, the request must transition to status=failed with error_code=INVALID_URL.
- If get_transcripts.lang is omitted by the caller, the service must use default 'en' and persist transcript_requests.lang='en'. If provided, persist exactly the provided code (no silent overrides).
- If a videos row does not exist for normalized_video_id, create it with status=active and canonical_url derived from the id; otherwise reuse the existing row.
- A transcript track is uniquely identified by (video_id, lang). On a successful fetch, upsert transcript_tracks to status=available, set last_fetched_at, and replace transcript_segments for that track within a transaction.
- When transcript_tracks.status=available, transcript_tracks.segment_count must equal the count of transcript_segments rows for that track.
- enableParagraphs affects only formatting/cached response_text in transcript_requests; it must not change the underlying transcript_tracks/transcript_segments content.
- request_key must be computed from (normalized_video_id, lang, enableParagraphs) after normalization; identical requests must return the cached transcript_requests.response_text when transcript_requests.status=succeeded.
- If upstream indicates transcripts are disabled or unavailable for the requested language, set transcript_tracks.status=unavailable (with failure_reason) and fail the request with error_code=TRANSCRIPT_UNAVAILABLE.
- Status transitions must follow the declared lifecycle transitions; direct transitions skipping intermediate states are rejected.