# yt-dlp Video and Audio Downloader — local MCP environment

This backend stores normalized metadata about user-requested video URLs, discovered subtitle tracks per video, and the lifecycle of download jobs (video, audio, subtitles, and cleaned transcripts). Primary workflows are: ingest a URL (or reuse an existing video record), discover available subtitle languages/formats, and enqueue download jobs that produce file artifacts (stored on disk or object storage) with auditable status and errors.

Repository: https://github.com/daniellopez-2/Youtube-Download
Homepage: https://smithery.ai/server/@daniellopez-2/youtube-download

## Datastore

- `videos.json` — Canonical representation of a video/resource URL and extracted metadata used to power listing subtitle languages and to scope downloads. (17 rows; fields: ['id', 'source_url', 'canonical_url', 'extractor', 'extractor_video_id', 'title', 'duration_seconds', 'webpage_url', 'status', 'last_error_code', 'last_error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['new', 'metadata_fetched', 'subtitles_fetched', 'error']
  - constraint: unique(canonical_url)
  - constraint: duration_seconds is null OR duration_seconds >= 0
  - constraint: status in ('new','metadata_fetched','subtitles_fetched','error')
- `subtitle_tracks.json` — Available subtitle/caption tracks for a video, including auto-generated captions and the set of supported formats per language. (17 rows; fields: ['id', 'video_id', 'language_code', 'is_auto_generated', 'track_name', 'available_formats', 'source', 'discovered_at', 'created_at', 'updated_at'])
  - lifecycle `source`: ['manual', 'automatic']
  - constraint: fk(video_id) references videos(id) on delete cascade
  - constraint: unique(video_id, language_code, is_auto_generated)
  - constraint: json_array_length(available_formats) >= 1
  - constraint: source in ('manual','automatic')
- `download_jobs.json` — A queued/running job to download a video, audio, subtitles, or a cleaned transcript derived from subtitles. (18 rows; fields: ['id', 'video_id', 'job_type', 'requested_resolution', 'requested_language', 'subtitle_fallback_to_auto', 'status', 'attempt_count', 'max_attempts', 'runner_host', 'started_at', 'finished_at', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(video_id) references videos(id) on delete cascade
  - constraint: job_type in ('video','audio','subtitles','transcript')
  - constraint: requested_resolution is null OR requested_resolution in ('480p','720p','1080p','best')
  - constraint: attempt_count >= 0
- `artifacts.json` — Files produced by download jobs (video/audio/subtitle files and cleaned transcript text), with storage location and basic metadata. (19 rows; fields: ['id', 'job_id', 'video_id', 'artifact_type', 'language_code', 'resolution', 'format', 'storage_backend', 'local_path', 'object_url', 'byte_size', 'sha256', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['creating', 'available', 'deleted', 'error']
  - constraint: fk(job_id) references download_jobs(id) on delete cascade
  - constraint: fk(video_id) references videos(id) on delete cascade
  - constraint: CHECK( (storage_backend='local_fs' AND local_path is not null AND object_url is null) OR (storage_backend='object_store' AND object_url is not null AND local_path is null) )
  - constraint: byte_size is null OR byte_size >= 0
- `subtitle_download_preferences.json` — Per-video preference mapping to choose between regular vs auto-generated subtitles when a language exists in both, and to record last successful format selection. (18 rows; fields: ['id', 'video_id', 'language_code', 'prefer_auto_generated', 'last_successful_format', 'created_at', 'updated_at'])
  - constraint: fk(video_id) references videos(id) on delete cascade
  - constraint: unique(video_id, language_code)

## Business rules enforced by the tools

- For any tool call with parameter url, the system must upsert a videos row by canonical_url (creating it if absent) and store the original source_url for traceability.
- list_subtitle_languages(url) must ensure subtitle discovery has run for the video: if videos.status is 'new' or 'metadata_fetched', refresh subtitle_tracks from the extractor and then set videos.status to 'subtitles_fetched' (or 'error' on failure).
- list_subtitle_languages(url) returns languages by reading subtitle_tracks filtered by video_id, including both manual and auto-generated entries and their available_formats.
- download_video(url, resolution) must create a download_jobs row with job_type='video' and requested_resolution set to the provided enum value, defaulting to '720p' when omitted.
- download_audio(url) must create a download_jobs row with job_type='audio' and requested_resolution=null.
- download_video_subtitles(url, language) must create a download_jobs row with job_type='subtitles', requested_language set to the provided language when present; if language is omitted, the worker must select a best-available language using subtitle_download_preferences when present or default to 'en' if available otherwise the first available track.
- download_video_subtitles(url, language) must set subtitle_fallback_to_auto=true and the worker must attempt manual subtitles first; if unavailable for that language, it must try auto-generated subtitles for that language before failing.
- download_transcript(url, language) must create a download_jobs row with job_type='transcript' and requested_language defaulting to 'en' when omitted; the worker must download subtitles first (manual then auto fallback) and then generate a transcript artifact by removing timestamps/markup.
- When a download job transitions to status='succeeded', at least one artifacts row must be created with status='available' and storage_backend consistent with the deployment (local_fs or object_store).
- A download_jobs row may only transition according to the declared lifecycle transitions; workers must not move a job from 'succeeded' or 'cancelled' back to another status.
- At most one running job per (video_id, job_type, requested_resolution, requested_language) should exist at a time; if a new request matches an existing queued/running job, the API should return the existing job instead of creating a duplicate.
- FK integrity must be enforced: subtitle_tracks.video_id, download_jobs.video_id, artifacts.job_id, artifacts.video_id, and subtitle_download_preferences.video_id must reference existing parent rows, with cascading deletes removing dependent rows.
- Artifacts must satisfy storage invariants: exactly one of local_path or object_url is populated based on storage_backend; transcript_text artifacts must have format='txt' (or null) and non-null language_code.