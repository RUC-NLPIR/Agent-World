# Unity MCP Integration — local MCP environment

This backend models a Unity MCP bridge that maintains registered Unity Editor connections, tracks project/scene snapshots, and provides a virtualized view of the Unity project's Assets filesystem. It also records editor logs and a full audit trail of tool invocations (including code execution and file mutations) for debugging, security, and reproducibility workflows.

Repository: https://github.com/quazaai/UnityMCPIntegration
Homepage: https://smithery.ai/server/@quazaai/unitymcpintegration

## Datastore

- `unity_editor_sessions.json` — Registered/active Unity Editor connections to the MCP server. Used by verify_connection and as the anchor for editor/project state, scene snapshots, logs, and tool invocations. (12 rows; fields: ['id', 'status', 'connection_name', 'mcp_client_id', 'unity_version', 'project_path', 'assets_root_path', 'project_guid', 'last_heartbeat_at', 'last_seen_scene_path', 'last_scene_snapshot_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['connected', 'disconnected', 'stale', 'terminated']
  - constraint: unique(project_guid, connection_name) where project_guid is not null and connection_name is not null
  - constraint: last_heartbeat_at <= now() (server time) when set
  - constraint: assets_root_path like '%/Assets' when set
- `scene_snapshots.json` — Captured representations of the current Unity scene state, including root objects and optionally full hierarchy. Used to serve get_current_scene_info and get_game_objects_info without requiring repeated deep queries to Unity. (12 rows; fields: ['id', 'session_id', 'status', 'scene_path', 'scene_name', 'active_build_target', 'capture_detail_level', 'captured_at', 'root_objects', 'hierarchy', 'instance_index', 'created_at', 'updated_at'])
  - lifecycle `status`: ['captured', 'superseded', 'invalid']
  - constraint: fk(session_id) references unity_editor_sessions(id) on delete cascade
  - constraint: capture_detail_level in ('RootObjectsOnly','FullHierarchy')
  - constraint: captured_at <= now()
  - constraint: hierarchy is null when capture_detail_level = 'RootObjectsOnly'
- `project_entries.json` — Virtualized index of files/directories under a Unity project's Assets folder, including metadata needed for list/search/tree/info and for safe file IO. Backed by periodic scans and/or on-demand stat calls. Used by read_file/read_multiple_files/write_file/edit_file/list_directory/directory_tree/search_files/get_file_info/find_assets_by_type. (17 rows; fields: ['id', 'session_id', 'status', 'path', 'absolute_path', 'entry_type', 'parent_path', 'name', 'extension', 'size_bytes', 'content_hash_sha256', 'last_modified_at', 'asset_type', 'is_text', 'created_at', 'updated_at'])
  - lifecycle `status`: ['present', 'deleted', 'ignored']
  - constraint: fk(session_id) references unity_editor_sessions(id) on delete cascade
  - constraint: unique(session_id, path)
  - constraint: path does not start with '/'
  - constraint: path must not contain '..' segments after normalization
- `editor_logs.json` — Unity Editor log entries ingested/observed by the MCP server for querying and filtering via get_logs. (18 rows; fields: ['id', 'session_id', 'log_type', 'message', 'stack_trace', 'timestamp', 'sequence_no', 'created_at', 'updated_at'])
  - constraint: fk(session_id) references unity_editor_sessions(id) on delete cascade
  - constraint: timestamp <= now() + interval '5 minutes' (allow small clock skew)
  - constraint: unique(session_id, sequence_no) where sequence_no is not null
- `tool_invocations.json` — Audit trail of all MCP tool calls executed against Unity: inputs, outputs (redacted if needed), duration, and success/failure. Covers execute_editor_command and all file/scene/log tools for observability and safety review. (19 rows; fields: ['id', 'session_id', 'status', 'tool_name', 'request_params', 'response_body', 'error_message', 'error_details', 'duration_ms', 'related_scene_snapshot_id', 'related_entry_ids', 'file_path', 'paths', 'code', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(session_id) references unity_editor_sessions(id) on delete cascade
  - constraint: duration_ms >= 0 when not null
  - constraint: tool_name in supported tool enum
  - constraint: file_path must not contain '..' segments after normalization when set

## Business rules enforced by the tools

- verify_connection succeeds only if there exists at least one unity_editor_sessions row with status='connected' and last_heartbeat_at within the server-defined staleness window (e.g., 30s); otherwise it returns a failure and logs a tool_invocations row with status='failed'.
- get_editor_state reads from the currently connected session and returns project_path, unity_version, and last_seen_scene_path from unity_editor_sessions; if no connected session exists, the call fails.
- get_current_scene_info(detailLevel) must return data derived from the latest scene_snapshots row for the active session; if the latest snapshot capture_detail_level is less detailed than requested (RootObjectsOnly < FullHierarchy), the server must capture a new snapshot with capture_detail_level=FullHierarchy and mark the previous latest snapshot as superseded.
- get_game_objects_info(instanceIDs, detailLevel) must validate instanceIDs has minItems=1 and all IDs are numeric; it returns nodes by resolving instanceIDs against scene_snapshots.instance_index or hierarchy for the latest snapshot, and any missing instanceID must be reported as not found (without failing the entire request unless all are missing).
- get_logs(types, count, fields, messageContains, stackTraceContains, timestampAfter, timestampBefore) must enforce 1 <= count <= 1000 when count is provided; timestampAfter and timestampBefore must parse as ISO datetimes and timestampAfter <= timestampBefore when both provided; results are filtered by session_id of the active connected session and ordered by timestamp desc then sequence_no desc.
- read_file(path) and read_multiple_files(paths) may only access files under the Assets root of the active session; any absolute path must be normalized and proven to be within assets_root_path; otherwise the call fails and is recorded in tool_invocations.
- write_file(path, content) must create or overwrite only within Assets; it must upsert a project_entries row for that path with entry_type='file', status='present', size_bytes=byte_length(content), last_modified_at set to now(), and update content_hash_sha256; if parent directories do not exist in project_entries, they must be created as entry_type='directory' with status='present'.
- edit_file(path, edits, dryRun) is allowed only for project_entries where entry_type='file' and is_text=true; each edit requires exact match of oldText; if any oldText is not found, the operation must fail atomically (no partial edits) unless the implementation explicitly documents partial mode (not in this tool surface).
- edit_file(dryRun=true) must not persist changes to disk or to project_entries.size_bytes/content_hash_sha256/last_modified_at; it may persist a tool_invocations row with response_body containing a diff preview.
- list_directory(path) and directory_tree(path, maxDepth) must normalize empty string to Assets root; maxDepth default is 5 and must be >= -1; maxDepth=-1 means unlimited but the server must apply an internal safety cap (e.g., max nodes) to prevent runaway traversal.
- search_files(path, pattern, excludePatterns) must treat excludePatterns default as an empty array and apply excludes after includes; results must be limited by an internal cap (e.g., 10k) and recorded in tool_invocations.response_body as truncated when applicable.
- get_file_info(path) must return metadata derived from project_entries when present; if not indexed, the server may stat the filesystem and then create/update the corresponding project_entries row before responding.
- find_assets_by_type(assetType, searchPath, maxDepth) must match against project_entries.asset_type case-sensitively or per Unity conventions (implementation-defined) and restrict to entry_type='file' and status='present'; maxDepth default is 1 and must be -1 or >=1.
- execute_editor_command(code) must record the submitted code in tool_invocations.code (or a secure hash if redaction is enabled); the server must reject empty code (minLength=1) and may enforce an additional maximum length quota (e.g., <= 200k) to protect the editor.