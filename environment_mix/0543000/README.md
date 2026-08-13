# Youtube Transcript — local MCP environment

This backend stores requests for YouTube video transcripts and the resulting transcript payloads segmented into timed cues. The main workflow is: accept a transcript request (url + preferred language), resolve the canonical YouTube video id, fetch/parse the transcript (or fail), store the attempt, and return the latest successful transcript for that video/language when available.

Repository: https://github.com/jkawamoto/mcp-youtube-transcript
Homepage: https://smithery.ai/server/@jkawamoto/mcp-youtube-transcript

## Datastore

- `videos.json` — Canonical YouTube video records resolved from user-supplied URLs. Used to normalize different URL formats to a single video_id and to attach transcripts and fetch attempts. (31 rows; fields: ['id', 'youtube_video_id', 'canonical_url', 'title', 'channel_id', 'created_at', 'updated_at'])
  - constraint: unique(youtube_video_id)
  - constraint: canonical_url must start with 'https://www.youtube.com/watch' or 'https://youtu.be/' after normalization
  - constraint: youtube_video_id length between 6 and 32 (implementation-defined, must be non-empty)
- `transcript_requests.json` — An immutable-ish log of get_transcript calls (url + preferred language) and their execution outcomes. Supports caching, rate limiting, and debugging. (33 rows; fields: ['id', 'raw_url', 'requested_lang', 'normalized_lang', 'video_id', 'status', 'transcript_id', 'served_from_cache', 'error_code', 'error_message', 'http_status', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'not_found', 'no_transcript', 'invalid_url', 'rate_limited', 'failed']
  - constraint: requested_lang non-empty, max length 16
  - constraint: normalized_lang = lower(trim(requested_lang)) with '_' converted to '-'
  - constraint: http_status between 100 and 599 when not null
  - constraint: duration_ms >= 0 when not null
- `transcripts.json` — A transcript rendition for a video and language. Stores metadata and points to cue segments. (33 rows; fields: ['id', 'video_id', 'lang', 'is_generated', 'source', 'status', 'cue_count', 'full_text', 'checksum_sha256', 'fetched_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded', 'deleted']
  - constraint: unique(video_id, lang, checksum_sha256) where checksum_sha256 is not null
  - constraint: cue_count >= 0
  - constraint: lang non-empty, max length 16
  - constraint: source in ('youtube_transcript_api','scraped','unknown')
- `transcript_cues.json` — Timed transcript cue segments (start time, duration, text). This is the primary payload returned to callers. (30 rows; fields: ['id', 'transcript_id', 'seq', 'start_seconds', 'duration_seconds', 'text', 'created_at', 'updated_at'])
  - constraint: unique(transcript_id, seq)
  - constraint: seq >= 1
  - constraint: start_seconds >= 0
  - constraint: duration_seconds is null or duration_seconds >= 0

## Business rules enforced by the tools

- get_transcript(url, lang) must create a transcript_requests row with raw_url=url and requested_lang=lang (or 'en' if omitted) before attempting any upstream fetch.
- The service must normalize and validate url; if a YouTube video id cannot be extracted, the request status must transition to invalid_url and no videos/transcripts rows may be created.
- For a valid video id, the service must upsert videos(youtube_video_id) and set transcript_requests.video_id accordingly.
- Language matching must use normalized_lang; if lang is omitted it must default to 'en'.
- If an active transcript exists for (video_id, normalized_lang), the service may return it and must set transcript_requests.status='succeeded', served_from_cache=true, and transcript_id to the reused transcript.
- If no cached transcript is served, transcript_requests must transition queued -> running before upstream access, and must finish in exactly one terminal status: succeeded, not_found, no_transcript, invalid_url, rate_limited, or failed.
- On succeeded: a transcripts row must be created with status='active', fetched_at set, and transcript_cues inserted with contiguous seq values starting at 1; cue_count must equal the number of inserted cues.
- When inserting a new active transcript for the same (video_id, lang), any existing active transcript must be transitioned to superseded atomically (ensuring at most one active transcript).
- On no_transcript (e.g., transcripts disabled/unavailable): do not create transcripts/transcript_cues; record error_code and optionally http_status=404.
- On rate_limited: do not create transcripts/transcript_cues; record http_status=429 and error_code indicating the limiter source; duration_ms must still be recorded if known.
- Data integrity: transcript_cues.transcript_id must reference an existing transcripts row; deleting a transcript must either cascade delete cues or mark transcript status='deleted' while retaining cues for audit (implementation must choose one and enforce consistently).
- Operational constraint: duration_ms must be non-negative for all requests where populated.