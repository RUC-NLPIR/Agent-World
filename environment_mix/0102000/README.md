# MagicSlides Server — local MCP environment

This backend powers a service that (1) fetches transcripts for YouTube videos and (2) generates PowerPoint presentations from user-provided text or a YouTube URL. The main workflow is: accept a request, optionally fetch/store a transcript, enqueue a PPT generation job, store the produced PPT file and expose job outputs for later retrieval/observability.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@IndianAppGuy/magicslide-mcp

## Datastore

- `access_keys.json` — Represents customer access identifiers (accessId) used to authenticate/authorize requests and apply quota/rate limits. (20 rows; fields: ['id', 'access_id', 'label', 'status', 'daily_request_limit', 'daily_ppt_limit', 'daily_transcript_limit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'revoked']
  - constraint: unique(access_id)
  - constraint: daily_request_limit >= 0
  - constraint: daily_ppt_limit >= 0
  - constraint: daily_transcript_limit >= 0
- `youtube_transcripts.json` — Stores normalized YouTube URL metadata and fetched transcript content for reuse/caching. (31 rows; fields: ['id', 'yt_url', 'video_id', 'language', 'transcript_text', 'transcript_segments', 'source', 'status', 'error_code', 'error_message', 'fetched_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'fetched', 'unavailable', 'error']
  - constraint: unique(video_id, language)
  - constraint: status = 'fetched' implies transcript_text is not null
  - constraint: expires_at is null or expires_at > created_at
- `ppt_generations.json` — Represents a request to generate a PowerPoint deck from user text or a YouTube URL, including job execution state and resulting file metadata. (46 rows; fields: ['id', 'access_key_id', 'user_text', 'input_type', 'youtube_transcript_id', 'status', 'provider', 'ppt_title', 'slide_count', 'output_format', 'output_storage_bucket', 'output_storage_key', 'output_download_url', 'output_sha256', 'output_bytes', 'error_code', 'error_message', 'queued_at', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(access_key_id) references access_keys(id)
  - constraint: foreign key(youtube_transcript_id) references youtube_transcripts(id)
  - constraint: input_type in ('text','youtube_url')
  - constraint: output_bytes is null or output_bytes >= 0
- `api_requests.json` — Immutable log of tool invocations for auditing, debugging, rate limiting, and billing/usage enforcement. (38 rows; fields: ['id', 'access_key_id', 'tool_name', 'request_body', 'response_body', 'http_status', 'success', 'latency_ms', 'ppt_generation_id', 'youtube_transcript_id', 'client_ip', 'user_agent', 'created_at', 'updated_at'])
  - lifecycle `success`: ['true', 'false']
  - constraint: foreign key(access_key_id) references access_keys(id)
  - constraint: foreign key(ppt_generation_id) references ppt_generations(id)
  - constraint: foreign key(youtube_transcript_id) references youtube_transcripts(id)
  - constraint: tool_name in ('create_ppt_from_text','get_youtube_transcript')

## Business rules enforced by the tools

- create_ppt_from_text must reject requests where accessId does not match an access_keys.access_id with status='active'.
- create_ppt_from_text must create a ppt_generations row per call and link it from api_requests.ppt_generation_id.
- create_ppt_from_text must set ppt_generations.input_type='youtube_url' if userText parses as a YouTube URL; otherwise 'text'.
- If ppt_generations.input_type='youtube_url', the service must attempt to resolve a youtube_transcripts row by (video_id, language) and reuse it if status='fetched' and (expires_at is null or expires_at > now). Otherwise it must create/update a youtube_transcripts row with status transitioning pending->(fetched|unavailable|error).
- get_youtube_transcript must upsert/read youtube_transcripts by parsed video_id (and language when applicable) and return transcript_text when status='fetched'; it must return a non-2xx/typed error when status in ('unavailable','error').
- A ppt_generations row may transition only according to the declared lifecycle transitions; once succeeded/failed/cancelled, it is immutable except for attaching output_download_url expiration refresh metadata (updated_at change).
- When ppt_generations.status='succeeded', output_storage_key, output_download_url, and finished_at must be non-null; when status='failed', error_code and finished_at must be non-null.
- Per access_keys, enforce daily_request_limit across all api_requests for the last 24 hours; enforce daily_ppt_limit across create_ppt_from_text calls; enforce daily_transcript_limit across get_youtube_transcript calls. If exceeded, reject the call and log an api_requests row with success=false and http_status=429.
- api_requests.request_body must include all required tool parameters exactly as received: create_ppt_from_text requires userText and accessId; get_youtube_transcript requires ytUrl.
- youtube_transcripts.unique(video_id, language) must be maintained; if language is unknown, store language as null and treat unique(video_id, null) as unique per database semantics (or normalize to 'und').