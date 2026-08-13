# Desktop Commander — local MCP environment

Desktop Commander is a local-agent backend that manages terminal execution sessions, file-system operations within an allowlist, and safety controls like command blacklisting. The core workflows are: start/monitor/terminate command sessions; perform audited file operations (read/write/move/search/edit) scoped to allowed directories; and enforce safety policies (blocked commands, path allowlist) with complete operation logs for debugging and accountability.

Repository: https://github.com/sondotpin/DesktopCommanderMCP
Homepage: https://smithery.ai/server/@sondotpin/desktopcommandermcp

## Datastore

- `workspaces.json` — Represents a single Desktop Commander server instance / logical environment. Stores security policy such as allowed directories and default timeouts used to validate and execute tool calls. (12 rows; fields: ['id', 'name', 'status', 'allowed_directories', 'default_command_timeout_ms', 'default_search_timeout_ms', 'max_command_timeout_ms', 'max_search_timeout_ms', 'max_search_results', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: default_command_timeout_ms >= 1
  - constraint: default_search_timeout_ms >= 1
  - constraint: max_command_timeout_ms >= default_command_timeout_ms
- `blocked_commands.json` — Command blacklist entries used to deny execution of dangerous or disallowed commands. Supports block_command, unblock_command, and list_blocked_commands. (26 rows; fields: ['id', 'workspace_id', 'command', 'status', 'blocked_reason', 'created_at', 'updated_at'])
  - lifecycle `status`: ['blocked', 'unblocked']
  - constraint: unique(workspace_id, command)
  - constraint: length(trim(command)) > 0
- `terminal_sessions.json` — Represents an executed terminal command and its OS process. Enables execute_command, read_output, force_terminate, and list_sessions. (33 rows; fields: ['id', 'workspace_id', 'os_pid', 'command', 'timeout_ms', 'cwd', 'status', 'exit_code', 'started_at', 'ended_at', 'last_output_offset', 'created_at', 'updated_at'])
  - lifecycle `status`: ['starting', 'running', 'exited', 'timed_out', 'terminated', 'failed']
  - constraint: unique(workspace_id, os_pid)
  - constraint: timeout_ms >= 1
  - constraint: last_output_offset >= 0
  - constraint: os_pid >= 1
- `terminal_output_chunks.json` — Append-only captured stdout/stderr chunks for terminal sessions. Enables incremental read_output and post-hoc auditing/debugging. (31 rows; fields: ['id', 'session_id', 'stream', 'seq', 'content', 'byte_count', 'created_at', 'updated_at'])
  - constraint: unique(session_id, seq)
  - constraint: byte_count >= 0
  - constraint: length(content) >= 0
- `fs_operations.json` — Audit log of file system and URL read operations. Powers observability and enforces policy (allowed directories, size limits) consistently across read_file/read_multiple_files/write_file/create_directory/list_directory/move_file/search_files/search_code/get_file_info/edit_block. (38 rows; fields: ['id', 'workspace_id', 'op_type', 'status', 'path', 'paths', 'destination', 'pattern', 'file_pattern', 'ignore_case', 'include_hidden', 'context_lines', 'max_results', 'timeout_ms', 'is_url', 'block_content', 'content_bytes_written', 'result_summary', 'error_message', 'started_at', 'ended_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'denied', 'cancelled']
  - constraint: context_lines is null or context_lines >= 0
  - constraint: max_results is null or (max_results >= 1 and max_results <= (select max_search_results from workspaces where id = workspace_id))
  - constraint: timeout_ms is null or timeout_ms >= 1
  - constraint: content_bytes_written is null or content_bytes_written >= 0

## Business rules enforced by the tools

- execute_command(command, timeout_ms): before creating a terminal_sessions row, the server must check blocked_commands where workspace_id matches and status='blocked' and command equals the normalized input; if blocked, the tool must not execute and must record a terminal_sessions row with status='failed' OR a fs_operations-style audit entry with status='denied' (implementation choice), including an error_message.
- execute_command: timeout_ms defaults to workspaces.default_command_timeout_ms when omitted, and must be <= workspaces.max_command_timeout_ms; otherwise deny the request.
- read_output(pid): must resolve pid to an active terminal_sessions row by (workspace_id, os_pid). If not found, return an error and do not create output chunks.
- read_output: must only return output that has not yet been acknowledged, using terminal_sessions.last_output_offset and terminal_output_chunks ordering; after returning output, last_output_offset must advance monotonically (never decrease).
- force_terminate(pid): only allowed for sessions in status in ('starting','running','timed_out'); on success set status='terminated' and ended_at is not null.
- list_sessions: returns terminal_sessions where status in ('starting','running','timed_out') (or a policy-defined 'active' set).
- list_processes: reads directly from the OS process table; it does not require persistence, but any optional auditing should create a fs_operations row with op_type='list_allowed_directories' is not appropriate—if audited, add a separate op_type in code or reuse a generic audit sink outside this model.
- kill_process(pid): must not allow killing a PID that maps to a managed terminal_sessions row unless the tool force_terminate is used; if it kills an arbitrary PID, the server should log an audit event outside terminal_sessions or extend fs_operations (not required by tool surface).
- block_command(command): upserts blocked_commands(workspace_id, command) setting status='blocked'.
- unblock_command(command): updates blocked_commands(workspace_id, command) setting status='unblocked' (row is retained for audit).
- list_blocked_commands: returns blocked_commands where workspace_id matches and status='blocked'.
- For all filesystem tools with a path/source/destination: the backend must validate that every referenced filesystem path is under one of workspaces.allowed_directories; otherwise the operation must be denied and fs_operations.status='denied' with error_message set.
- read_file(path, isUrl): if isUrl=true, the allowlist directory check is skipped but the URL must be http/https and subject to a server-defined maximum response size; record fs_operations with is_url=true.
- read_multiple_files(paths): must attempt each path independently; any per-file failure must be reflected in fs_operations.result_summary while still allowing other files to succeed.
- search_files(path, pattern, timeoutMs): timeoutMs defaults to workspaces.default_search_timeout_ms and must be <= workspaces.max_search_timeout_ms; otherwise deny.
- search_code(path, pattern, ...): maxResults must be <= workspaces.max_search_results; contextLines must be >= 0; ignoreCase/includeHidden default to false when omitted; record all provided parameters into fs_operations fields.
- write_file(path, content) and edit_block(blockContent): must only write within allowed directories; on success record content_bytes_written >= 0 and status='succeeded'; on verification failure set status='failed' with an error_message.
- move_file(source, destination): both paths must pass allowlist validation; the operation must be atomic from the API perspective (either succeeds and status='succeeded', or fails and status='failed' with no partial rename/move recorded as success).
- get_file_info(path) and list_directory(path): must validate allowlist and record fs_operations entries with status reflecting success/denial/failure.
- list_allowed_directories: returns workspaces.allowed_directories for the active workspace; should create an fs_operations row with op_type='list_allowed_directories' and status='succeeded' (optional but supported by this schema).
- Foreign key integrity: deleting a workspace is only allowed when status transitions to 'deleted'; rows in blocked_commands, terminal_sessions, terminal_output_chunks, and fs_operations must remain for audit (soft-delete workspace only).