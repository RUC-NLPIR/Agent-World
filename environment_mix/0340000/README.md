# Think Tool Server — local MCP environment

This backend stores per-session thought logs for a "think tool" service. The main workflow is: a client creates/uses a session (implicit via auth/connection), appends thought entries, can list them, clear them (soft-delete via purge), and query session-level statistics.

Repository: https://github.com/ddkang1/mcp-think-tool
Homepage: https://smithery.ai/server/@ddkang1/mcp-think-tool

## Datastore

- `api_keys.json` — API credentials used to authenticate callers and scope sessions. Supports revocation and basic quotas/limits per key. (12 rows; fields: ['id', 'key_hash', 'key_prefix', 'label', 'status', 'rate_limit_rps', 'daily_thought_limit', 'created_at', 'updated_at', 'revoked_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(key_hash)
  - constraint: unique(key_prefix)
  - constraint: rate_limit_rps > 0
  - constraint: daily_thought_limit >= 0
- `sessions.json` — Represents a logical "current session" for which thoughts are recorded, listed, cleared, and summarized. (12 rows; fields: ['id', 'api_key_id', 'external_session_key', 'status', 'thought_count', 'last_thought_at', 'cleared_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'cleared', 'expired', 'closed']
  - constraint: foreign key (api_key_id) references api_keys(id)
  - constraint: unique(api_key_id, external_session_key) where external_session_key is not null
  - constraint: thought_count >= 0
- `thoughts.json` — Append-only thought log entries within a session. Clearing a session purges (soft-deletes) thoughts but preserves auditability. (18 rows; fields: ['id', 'session_id', 'sequence_no', 'thought', 'status', 'char_len', 'token_estimate', 'purged_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'purged']
  - constraint: foreign key (session_id) references sessions(id)
  - constraint: unique(session_id, sequence_no)
  - constraint: char_len >= 0
  - constraint: token_estimate is null or token_estimate >= 0
- `session_events.json` — Audit trail for session-level actions such as clearing thoughts. Used to support debugging, compliance, and operational metrics. (12 rows; fields: ['id', 'session_id', 'event_type', 'event_payload', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['think_appended', 'thoughts_cleared', 'session_created', 'session_closed']
  - constraint: foreign key (session_id) references sessions(id)

## Business rules enforced by the tools

- think(thought) must create a thoughts row with status='active', session_id resolved from the current authenticated session context, and sequence_no = (max(sequence_no) + 1) within that session.
- think(thought) must reject if api_keys.status != 'active'.
- think(thought) must treat missing thought as default '' and still append a row; char_len must equal length(thought).
- think(thought) must enforce length(thought) <= 50000 and reject requests exceeding this limit.
- get_thoughts must return all thoughts for the current session where status='active', ordered by sequence_no ascending.
- clear_thoughts must mark all thoughts in the current session with status='active' as status='purged' and set purged_at to now; it must set sessions.cleared_at=now, sessions.status='cleared', and sessions.thought_count=0.
- get_thought_stats must compute (or use cached) total_active_thoughts, total_chars=sum(char_len), first_thought_at=min(created_at), last_thought_at=max(created_at) over thoughts with status='active' for the current session.
- sessions.thought_count must always equal the count of thoughts where thoughts.session_id=sessions.id and thoughts.status='active' (maintained transactionally or via background reconciliation).
- A session is uniquely identified per api_key by external_session_key when provided; otherwise the system may use a single implicit active session per api_key (enforced by allowing at most one sessions row with status in ('active','cleared') and external_session_key is null per api_key).
- Quota enforcement: for each api_key, the number of thoughts appended in a UTC day must be <= api_keys.daily_thought_limit when the limit is > 0; otherwise reject think requests with a quota-exceeded error.
- Rate limiting: requests associated with an api_key must not exceed api_keys.rate_limit_rps averaged over a short window; on violation, reject with a rate-limit error.
- FK integrity must be enforced: deleting an api_key is disallowed while sessions exist; deleting a session is disallowed while thoughts exist (use status transitions/expiration instead).
- Every successful think append must also insert a session_events row with event_type='think_appended' and payload including thought_id, char_len, and sequence_no; every clear must insert event_type='thoughts_cleared' with payload including number_purged.