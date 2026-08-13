# Gong MCP Server — local MCP environment

This backend stores Gong call metadata and the associated transcript content broken into speakers, topics, and timestamped sentences. The main workflows are syncing/importing calls from Gong, listing calls for clients, and retrieving structured transcripts for one or more calls.

Repository: https://github.com/kenazk/gong-mcp
Homepage: https://smithery.ai/server/@kenazk/gong-mcp

## Datastore

- `workspaces.json` — Tenant boundary for a Gong-connected organization; owns calls, transcripts, and API keys. (12 rows; fields: ['id', 'name', 'gong_account_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(gong_account_id) WHERE gong_account_id IS NOT NULL
  - constraint: name <> ''
- `api_keys.json` — API keys used to authenticate MCP clients to a workspace and apply quota/rate controls. (12 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'status', 'last_used_at', 'daily_call_limit', 'daily_call_count', 'daily_count_date', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: daily_call_limit >= 0
  - constraint: daily_call_count >= 0
- `calls.json` — Call metadata imported from Gong; used by list_calls and as the parent for transcript retrieval. (19 rows; fields: ['id', 'workspace_id', 'gong_call_id', 'title', 'started_at', 'ended_at', 'duration_seconds', 'status', 'participants', 'source', 'raw_metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['imported', 'processing_transcript', 'ready', 'failed', 'deleted']
  - constraint: unique(workspace_id, gong_call_id)
  - constraint: duration_seconds IS NULL OR duration_seconds >= 0
  - constraint: ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at
  - constraint: participants IS NOT NULL
- `call_transcripts.json` — Normalized transcript container per call, including speakers and extracted topics; used by retrieve_transcripts. (19 rows; fields: ['id', 'call_id', 'workspace_id', 'language', 'speaker_index', 'topics', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'ready', 'error', 'deleted']
  - constraint: unique(call_id)
  - constraint: topics IS NOT NULL
  - constraint: speaker_index IS NOT NULL
  - constraint: status <> 'error' OR error_message IS NOT NULL
- `transcript_sentences.json` — Timestamped sentence-level transcript segments for a call, including speaker ID; returned by retrieve_transcripts. (33 rows; fields: ['id', 'transcript_id', 'call_id', 'workspace_id', 'speaker_id', 'start_ms', 'end_ms', 'text', 'ordinal', 'confidence', 'created_at', 'updated_at'])
  - lifecycle `status`: []
  - constraint: unique(transcript_id, ordinal)
  - constraint: start_ms >= 0
  - constraint: end_ms >= start_ms
  - constraint: confidence IS NULL OR (confidence >= 0 AND confidence <= 1)

## Business rules enforced by the tools

- list_calls returns calls for the authenticated api_keys.workspace_id only; calls.status != 'deleted'.
- retrieve_transcripts accepts one or more call IDs (from request body or query); for each call, it returns transcript content only if calls.workspace_id matches the API key workspace and calls.status in ('ready','imported','processing_transcript','failed') and call_transcripts.status='ready'.
- For any call with call_transcripts.status != 'ready', retrieve_transcripts must return an explicit per-call error/empty transcript payload and must not return transcript_sentences rows.
- When a call_transcripts row is created, it must copy workspace_id from the parent calls.workspace_id; same for transcript_sentences.workspace_id and transcript_sentences.call_id.
- Transcript sentences must be contiguous in ordering: ordinal is unique per transcript; retrieval sorts by ordinal ascending. Gaps are allowed, but duplicates are rejected.
- speaker_id on transcript_sentences must exist as a key in call_transcripts.speaker_index for the same transcript_id; otherwise insertion is rejected.
- API key usage: each successful tool invocation increments api_keys.daily_call_count; if daily_call_count would exceed daily_call_limit, the request is rejected.
- At daily rollover (daily_count_date != today at 00:00:00Z), daily_call_count resets to 0 and daily_count_date is updated before evaluating quota.
- Deleting a call sets calls.status='deleted' and cascades to call_transcripts.status='deleted' (soft delete) and hides transcript_sentences from reads without physically deleting rows.
- FK integrity is enforced: calls.workspace_id references workspaces.id; call_transcripts.call_id references calls.id; transcript_sentences.transcript_id references call_transcripts.id.