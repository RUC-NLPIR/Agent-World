# Vertex AI Server — local MCP environment

This backend stores workspaces, API access, and an audit trail of LLM-assisted query runs that may use Google web search and optionally write results into a workspace-local virtual filesystem. Primary workflows are (1) run a query (direct or websearch/doc-focused) and persist the run, sources, and answer; (2) perform filesystem operations (read/write/edit/list/move/search/info/tree) with full operation logging and content versioning; (3) save answers/snippets/guidelines into files and associate them with the originating run.

Repository: https://github.com/shariqriazz/vertex-ai-mcp-server
Homepage: https://smithery.ai/server/@shariqriazz/vertex-ai-mcp-server

## Datastore

- `workspaces.json` — Tenant boundary for the MCP server: groups API keys, query runs, and a workspace-local virtual filesystem root. (12 rows; fields: ['id', 'name', 'status', 'google_project_id', 'vertex_model', 'allow_web_search', 'max_requests_per_day', 'max_files_bytes', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: vertex_model in ('gemini-1.5-pro-latest')
  - constraint: max_requests_per_day between 0 and 1000000
  - constraint: max_files_bytes between 0 and 1099511627776
- `api_keys.json` — API credentials used to authenticate requests to the MCP server per workspace; also stores per-key enablement and optional per-key limits. (18 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'status', 'last_used_at', 'requests_today', 'daily_request_limit_override', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete cascade
  - constraint: unique(workspace_id, name)
  - constraint: unique(key_hash)
  - constraint: requests_today >= 0
- `query_runs.json` — Normalized log of all LLM query tools (direct/websearch/docs/snippets/guidelines) including inputs, model configuration, outputs, and linkage to any file saved. (37 rows; fields: ['id', 'workspace_id', 'api_key_id', 'tool_name', 'status', 'query', 'topic', 'tech_stack', 'use_web_search', 'model_name', 'prompt_tokens', 'completion_tokens', 'latency_ms', 'answer_text', 'error_code', 'error_message', 'output_file_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete cascade
  - constraint: foreign key (api_key_id) references api_keys(id) on delete set null
  - constraint: foreign key (output_file_id) references fs_nodes(id) on delete set null
  - constraint: model_name in ('gemini-1.5-pro-latest')
- `web_sources.json` — Captured web search sources/snippets used to ground a query run. Enables traceability for websearch and doc-focused tools. (30 rows; fields: ['id', 'query_run_id', 'rank', 'url', 'title', 'snippet', 'is_official_doc', 'created_at', 'updated_at'])
  - lifecycle `is_official_doc`: ['true', 'false']
  - constraint: foreign key (query_run_id) references query_runs(id) on delete cascade
  - constraint: unique(query_run_id, rank)
  - constraint: rank between 1 and 50
  - constraint: url like 'http%'
- `fs_nodes.json` — Virtual filesystem index for each workspace: directories and files, their metadata, and current content pointer (versioned via fs_versions). Supports read/write/edit/list/tree/move/search/info tools and save_* tools. (32 rows; fields: ['id', 'workspace_id', 'parent_id', 'path', 'name', 'node_type', 'status', 'size_bytes', 'permissions_octal', 'created_at', 'updated_at', 'last_accessed_at', 'current_version_id'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete cascade
  - constraint: foreign key (parent_id) references fs_nodes(id) on delete restrict
  - constraint: foreign key (current_version_id) references fs_versions(id) on delete set null
  - constraint: unique(workspace_id, path)
- `fs_versions.json` — Immutable content versions for file nodes, enabling overwrite and edit operations with diffs and auditability. Also used for saved query outputs. (34 rows; fields: ['id', 'fs_node_id', 'created_by_run_id', 'op_type', 'encoding', 'content_text', 'content_sha256', 'diff_from_prev', 'created_at', 'updated_at'])
  - lifecycle `op_type`: ['write', 'edit', 'save_tool']
  - constraint: foreign key (fs_node_id) references fs_nodes(id) on delete cascade
  - constraint: foreign key (created_by_run_id) references query_runs(id) on delete set null
  - constraint: encoding in ('utf-8','utf-16','latin-1','ascii')
  - constraint: length(content_sha256)=64

## Business rules enforced by the tools

- Authentication: every tool invocation must authenticate via an api_keys record with status='active' and its workspace must be status='active'.
- Quota: creating a query_runs row increments api_keys.requests_today and must not exceed coalesce(api_keys.daily_request_limit_override, workspaces.max_requests_per_day); otherwise the run must be rejected and not inserted (or inserted as failed with error_code='quota_exceeded' per implementation choice).
- Web search gating: if a query tool requires web search (answer_query_websearch, explain_topic_with_docs, get_doc_snippets, generate_project_guidelines and all save_* variants that mention search), then workspaces.allow_web_search must be true; otherwise the run must fail with error_code='web_search_disabled'.
- Tool input validation: query_runs must satisfy required inputs by tool_name (query/topic/tech_stack); requests missing required inputs must not start a run and must not write any fs_versions.
- Source capture: if query_runs.use_web_search=true then at least 1 web_sources row must be created for the run before transitioning the run to status='succeeded'.
- Filesystem path safety: fs_nodes.path must be normalized and must not contain '..', empty segments, or null bytes; all filesystem tools must reject unsafe paths.
- Directory semantics: create_directory ensures a directory fs_nodes row exists (node_type='directory', status='active') for the given path; if a file already exists at that path, the operation must fail.
- File writes: write_file_content creates or overwrites a file by inserting a fs_versions row (op_type='write') and updating fs_nodes.current_version_id and size_bytes; it must enforce workspace max_files_bytes (sum of active file sizes) and reject writes that exceed it.
- Edits: edit_file_content must create a new fs_versions row (op_type='edit') and set diff_from_prev to a git-style diff; if no changes occur, it must either return a no-op diff and not create a new version, or create a version marked as identical (implementation must be consistent).
- Reads: read_file_content and read_multiple_files_content return content from fs_versions.content_text referenced by fs_nodes.current_version_id; if node is missing, deleted, or is a directory, the read must fail for that path.
- Moves/renames: move_file_or_directory must update fs_nodes.path/name and all descendant paths for directories atomically; it must enforce unique(workspace_id, path) and fail if the destination path exists.
- Listing/tree/search: list_directory_contents lists direct children by parent_id; get_directory_tree traverses descendants; search_filesystem performs case-insensitive substring match on name (and must honor provided exclude globs at query time even if not persisted).
- Info: get_filesystem_info returns metadata from fs_nodes plus timestamps; permissions_octal must be returned as stored.
- Save tools: save_* tools must (a) run the corresponding query tool behavior, (b) write answer_text to the target output_path using fs_versions.op_type='save_tool', and (c) set query_runs.output_file_id to the written file's fs_nodes.id before marking the run succeeded.
- Audit immutability: fs_versions rows are immutable after insert (updated_at must remain equal to created_at); content changes must always produce a new fs_versions row.
- Deletion: if a workspace is deleted, all dependent records must be deleted via FK cascades; filesystem nodes may be soft-deleted (status='deleted') but should still be physically removed on workspace deletion.