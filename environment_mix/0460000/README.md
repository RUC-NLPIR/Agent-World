# Prolog Execution and Querying — local MCP environment

This backend stores Prolog execution sessions, uploaded/compiled programs, and query runs against a Prolog engine. Main workflows are: (1) inspect available predicates (discover) from a given engine/session, (2) submit a Prolog program to compile/load into a session (exec), and (3) run queries against the currently loaded program and persist results (query).

Repository: https://github.com/snoglobe/prolog_mcp
Homepage: https://smithery.ai/server/@snoglobe/prolog_mcp

## Datastore

- `prolog_engines.json` — Configured Prolog engine instances (local embedded engine or remote RPC-backed) that can load programs, expose predicates, and execute queries. (12 rows; fields: ['id', 'name', 'engine_type', 'endpoint_url', 'default_session_ttl_seconds', 'max_program_bytes', 'max_query_chars', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'degraded', 'disabled']
  - constraint: unique(name)
  - constraint: default_session_ttl_seconds >= 60 and default_session_ttl_seconds <= 86400
  - constraint: max_program_bytes >= 1 and max_program_bytes <= 10485760
  - constraint: max_query_chars >= 1 and max_query_chars <= 100000
- `prolog_sessions.json` — Execution contexts for a Prolog engine. Programs are loaded into a session; discover/query operate over the session's currently loaded predicates. (18 rows; fields: ['id', 'engine_id', 'status', 'loaded_program_id', 'last_activity_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ready', 'busy', 'expired', 'failed']
  - constraint: foreign key(engine_id) references prolog_engines(id) on delete restrict
  - constraint: expires_at > created_at
  - constraint: last_activity_at >= created_at
- `prolog_programs.json` — Submitted Prolog programs (source text) that can be compiled/loaded into a session via exec. (17 rows; fields: ['id', 'engine_id', 'session_id', 'source_text', 'source_sha256', 'compile_status', 'compile_error', 'loaded_predicates_cache', 'created_at', 'updated_at'])
  - lifecycle `compile_status`: ['queued', 'compiling', 'loaded', 'error']
  - constraint: foreign key(engine_id) references prolog_engines(id) on delete restrict
  - constraint: foreign key(session_id) references prolog_sessions(id) on delete cascade
  - constraint: length(source_text) >= 1
  - constraint: unique(session_id, source_sha256)
- `prolog_queries.json` — Queries executed against a session (tool: query). Stores the query text, execution status, and serialized results. (18 rows; fields: ['id', 'engine_id', 'session_id', 'program_id', 'query_text', 'status', 'result_format', 'result_payload', 'error_message', 'started_at', 'finished_at', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key(engine_id) references prolog_engines(id) on delete restrict
  - constraint: foreign key(session_id) references prolog_sessions(id) on delete cascade
  - constraint: foreign key(program_id) references prolog_programs(id) on delete set null
  - constraint: length(query_text) >= 1
- `predicate_catalog_entries.json` — Materialized predicate inventory exposed by an engine or derived from a loaded program, used to serve discover efficiently and consistently. (18 rows; fields: ['id', 'engine_id', 'session_id', 'program_id', 'name', 'arity', 'signature', 'origin', 'is_dynamic', 'documentation', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale']
  - constraint: foreign key(engine_id) references prolog_engines(id) on delete restrict
  - constraint: foreign key(session_id) references prolog_sessions(id) on delete cascade
  - constraint: foreign key(program_id) references prolog_programs(id) on delete cascade
  - constraint: arity >= 0 and arity <= 255

## Business rules enforced by the tools

- Tool discover returns predicate_catalog_entries where engine_id matches the active engine and (session_id is null for global/builtins OR session_id matches the current session), and status='active'.
- Tool exec(program) creates a prolog_programs row with source_text=program and compile_status='queued', then transitions through 'compiling' to either 'loaded' or 'error'. On 'loaded', prolog_sessions.loaded_program_id must be set to that program id and prolog_sessions.last_activity_at updated.
- Tool exec must reject programs larger than prolog_engines.max_program_bytes for the session's engine.
- Tool query(query) creates a prolog_queries row with query_text=query and status='queued', then runs it by transitioning to 'running' and finally to 'succeeded' or 'failed' (or 'cancelled' if interrupted).
- Tool query must reject queries longer than prolog_engines.max_query_chars for the session's engine.
- A session in status 'expired' must not accept exec or query; callers must create/renew a session (implementation may auto-create a new session if none exists).
- When a new program is successfully loaded into a session, all predicate_catalog_entries for that session with origin='user_program' must be marked 'stale' and replaced/updated with entries derived from the new program, then marked 'active'.
- prolog_sessions.expires_at must be extended on successful exec and query (sliding TTL) but must never exceed created_at + prolog_engines.default_session_ttl_seconds unless explicitly configured.
- For any prolog_queries row: if status='succeeded' then result_payload must be non-null and error_message must be null; if status='failed' then error_message must be non-null.
- Foreign key integrity must be enforced: engine_id must exist for all sessions/programs/queries/predicate entries; session_id must exist for all programs/queries with that field set.