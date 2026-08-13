# Filesystem MCP Server — local MCP environment

This backend persists session-scoped configuration and an auditable log of filesystem operations performed through the MCP server. It tracks resolved paths, operation parameters, results, and error states so every tool call can be validated against a session default root and later inspected or replayed.

Repository: https://github.com/cyanheads/filesystem-mcp-server
Homepage: https://smithery.ai/server/@cyanheads/filesystem-mcp-server

## Datastore

- `sessions.json` — Ephemeral MCP client sessions. Stores the session-scoped default filesystem base path used to resolve relative paths in subsequent tools. Default is cleared on server restart (modeled by session lifecycle ending). (18 rows; fields: ['id', 'client_name', 'default_base_path', 'default_base_path_set_at', 'status', 'created_at', 'updated_at', 'ended_at'])
  - lifecycle `status`: ['active', 'ended']
  - constraint: status in ('active','ended')
  - constraint: default_base_path is null OR default_base_path is an absolute path
  - constraint: if status='ended' then ended_at is not null
- `filesystem_nodes.json` — Known filesystem paths observed/created/modified via the server. Acts as a materialized catalog for audit and quicker lookups; not necessarily a complete mirror of the OS filesystem. (18 rows; fields: ['id', 'canonical_path', 'node_type', 'exists_flag', 'size_bytes', 'content_hash_sha256', 'last_seen_at', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['present', 'deleted', 'unknown']
  - constraint: unique(canonical_path)
  - constraint: node_type in ('file','directory')
  - constraint: status in ('present','deleted','unknown')
  - constraint: size_bytes is null OR size_bytes >= 0
- `file_versions.json` — Content snapshots for files written or updated through the server. Enables auditability and supports targeted updates by referencing prior content hashes. (18 rows; fields: ['id', 'node_id', 'version_number', 'content_text', 'content_hash_sha256', 'byte_length', 'created_by_operation_id', 'created_at', 'updated_at'])
  - lifecycle `version_number`: []
  - constraint: foreign key (node_id) references filesystem_nodes(id)
  - constraint: version_number >= 1
  - constraint: byte_length >= 0
  - constraint: unique(node_id, version_number)
- `filesystem_operations.json` — Audit log of all tool invocations (read/write/update/list/create/delete/move/copy and setting defaults). Stores both raw parameters and resolved paths, plus outcomes and errors. (20 rows; fields: ['id', 'session_id', 'tool_name', 'status', 'parameters', 'resolved_base_path', 'source_path_input', 'source_path_resolved', 'destination_path_input', 'destination_path_resolved', 'node_id', 'destination_node_id', 'result_summary', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed']
  - constraint: foreign key (session_id) references sessions(id)
  - constraint: tool_name in ('read_file','set_filesystem_default','write_file','update_file','list_files','delete_file','delete_directory','create_directory','move_path','copy_path')
  - constraint: status in ('received','running','succeeded','failed')
  - constraint: if tool_name='move_path' or tool_name='copy_path' then source_path_resolved is not null and destination_path_resolved is not null
- `update_blocks.json` — Child table for update_file operations, storing ordered search/replace blocks and flags such as useRegex/replaceAll (modeled at the operation level and/or per-block). (18 rows; fields: ['id', 'operation_id', 'block_index', 'search', 'replace', 'use_regex', 'replace_all', 'created_at', 'updated_at'])
  - lifecycle `block_index`: []
  - constraint: foreign key (operation_id) references filesystem_operations(id) on delete cascade
  - constraint: block_index >= 0
  - constraint: unique(operation_id, block_index)

## Business rules enforced by the tools

- A session in status='ended' must not accept new filesystem_operations; tool handlers must create a new session instead.
- set_filesystem_default must only accept an absolute path; when executed successfully it updates sessions.default_base_path and sessions.default_base_path_set_at for that session.
- For any tool that accepts a path, the server must store both the input path (as provided) and the resolved absolute path in filesystem_operations.*_path_input and *_path_resolved.
- Relative paths must resolve against sessions.default_base_path at the time the operation starts; if default_base_path is null, relative paths are rejected with error_code='INVALID_PATH'.
- read_file succeeds only if the resolved path exists and is a file; on success it upserts filesystem_nodes(node_type='file', exists_flag=true, status='present', last_seen_at=now).
- write_file creates or overwrites a file; on success it upserts filesystem_nodes for the file and inserts a new file_versions row with version_number = previous max + 1 for that node.
- update_file requires the target file to exist; it must record one or more update_blocks rows (ordered) and on success must create a new file_versions snapshot reflecting the updated content.
- delete_file marks filesystem_nodes.exists_flag=false and status='deleted' on success; if the file was not previously known, it creates a node row with status='deleted' and exists_flag=false.
- create_directory on success upserts filesystem_nodes(node_type='directory', exists_flag=true, status='present').
- delete_directory when recursive=false must fail if the directory is not empty; the operation must be recorded with status='failed' and error_code='DIRECTORY_NOT_EMPTY'.
- move_path on success must update filesystem_nodes.canonical_path for the moved node (and for recursive children if directory) or mark old paths deleted and create new nodes; the operation must link node_id and destination_node_id accordingly.
- copy_path on success must create destination nodes (and file_versions snapshots for copied files when content is available); source nodes remain unchanged.
- list_files must enforce maxEntries default 50 and a hard upper bound (e.g., 1000) even if the client requests more; returned entry count must be stored in filesystem_operations.result_summary.entries_returned.
- filesystem_operations.status transitions must be enforced exactly as declared; finished_at is required for succeeded/failed and started_at is required for running/succeeded/failed.