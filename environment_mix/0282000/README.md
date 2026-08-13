# Terminal Controller — local MCP environment

This backend stores per-session terminal state (current working directory) and an auditable log of shell commands and file operations executed through the API. Primary workflows include executing commands with timeouts, navigating directories, listing directories, and reading/writing/modifying files with optional line-range addressing and substring-based edits.

Repository: https://github.com/GongRzhe/terminal-controller-mcp
Homepage: https://smithery.ai/server/@GongRzhe/terminal-controller-mcp

## Datastore

- `sessions.json` — Represents a terminal controller session with its current working directory and lifecycle. All commands and file operations are executed within a session context. (12 rows; fields: ['id', 'status', 'current_directory', 'root_directory', 'last_activity_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'closed']
  - constraint: current_directory <> ''
  - constraint: root_directory IS NULL OR root_directory <> ''
- `command_executions.json` — Stores each execute_command invocation, including stdout/stderr, exit code, and timeout behavior. Also serves get_command_history. (36 rows; fields: ['id', 'session_id', 'command', 'timeout_seconds', 'working_directory', 'status', 'pid', 'exit_code', 'stdout', 'stderr', 'started_at', 'finished_at', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'timed_out', 'cancelled']
  - constraint: timeout_seconds BETWEEN 1 AND 3600
  - constraint: command <> ''
  - constraint: exit_code IS NULL OR exit_code BETWEEN -255 AND 255
  - constraint: duration_ms IS NULL OR duration_ms >= 0
- `file_operations.json` — Audit log for file and directory operations: change_directory, list_directory, read_file, write_file, insert_file_content, delete_file_content, update_file_content. Stores request parameters, resolved paths, and summarized results. (33 rows; fields: ['id', 'session_id', 'operation_type', 'status', 'input_path', 'resolved_path', 'write_mode', 'content', 'start_row', 'end_row', 'as_json', 'row', 'rows', 'substring', 'result_summary', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'succeeded', 'failed']
  - constraint: FK(session_id) REFERENCES sessions(id) ON DELETE CASCADE
  - constraint: operation_type = 'get_current_directory' => input_path IS NULL
  - constraint: operation_type IN ('change_directory','list_directory','read_file','write_file','insert_file_content','delete_file_content','update_file_content') => input_path IS NOT NULL
  - constraint: start_row IS NULL OR start_row >= 0
- `fs_entries_cache.json` — Optional cache of directory listings and file metadata to speed repeated list_directory/read_file calls and to enable consistent responses across a session. Can be invalidated on writes/updates/inserts/deletes. (15 rows; fields: ['id', 'session_id', 'path', 'entry_type', 'status', 'payload', 'etag', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['valid', 'stale', 'invalid']
  - constraint: unique(session_id, path, entry_type)
  - constraint: FK(session_id) REFERENCES sessions(id) ON DELETE CASCADE

## Business rules enforced by the tools

- execute_command must create a command_executions row with status='queued' then transition to 'running' and finally one of ('succeeded','failed','timed_out','cancelled'); finished_at must be set for terminal statuses and duration_ms must be >= 0.
- get_command_history(count) returns the most recent command_executions for the active session ordered by created_at DESC limited to count, where count is clamped to 1..200.
- get_current_directory returns sessions.current_directory for the session and logs a file_operations row with operation_type='get_current_directory'.
- change_directory(path) must resolve the path against sessions.current_directory, verify it is an existing directory, update sessions.current_directory atomically, and log a file_operations row with operation_type='change_directory' including input_path and resolved_path.
- list_directory(path) must treat null path as sessions.current_directory; it may read/write fs_entries_cache for (session_id,resolved_path,entry_type='directory_listing') and must mark cache entries stale/invalid when a write/insert/update/delete affects a directory.
- write_file(path, content, mode) must enforce mode in {'overwrite','append'}, resolve path, perform the write, and log file_operations with write_mode and content; it must invalidate related fs_entries_cache entries for the file and its parent directory.
- read_file(path, start_row, end_row, as_json) must enforce start_row/end_row are null or >=0 and end_row>=start_row when both provided; it logs a file_operations record and stores only result_summary (not full contents) to avoid leaking large data into the DB.
- insert_file_content/delete_file_content/update_file_content must enforce exactly one of row or rows may be provided; if rows is provided it must be a set of unique non-negative integers; operations must log file_operations including substring when provided and invalidate related cache entries.
- All operations must be rejected when sessions.status='closed'; for sessions.status='suspended' read-only operations may be allowed but mutating operations (change_directory, write/insert/delete/update, execute_command) must be rejected.
- If sessions.root_directory is set, resolved_path for any tool that accepts a path must remain within root_directory; otherwise the request fails and the corresponding operation record must have status='failed' with error_message populated.