# Obsidian Integration Server — local MCP environment

This backend models an Obsidian vault integration layer that tracks vaults, markdown files, and user sessions (including which file is currently active) so the API can open, edit, append, delete, list, and search notes. It stores file metadata and content snapshots plus an audit trail of edit operations to support deterministic modifications and safe lifecycle transitions.

Repository: https://github.com/gregkonush/mcp-obsidian
Homepage: https://smithery.ai/server/@gregkonush/mcp-obsidian

## Datastore

- `vaults.json` — Registered Obsidian vaults accessible through the integration server. A vault groups files and provides the namespace for listing/searching/opening/editing. (12 rows; fields: ['id', 'name', 'root_path', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'read_only', 'disabled']
  - constraint: unique(name)
  - constraint: unique(root_path)
  - constraint: status in ('active','read_only','disabled')
  - constraint: root_path != ''
- `files.json` — Markdown notes and other vault files. Stores current content plus metadata used for open/list/search and edit operations. (19 rows; fields: ['id', 'vault_id', 'path', 'dir_path', 'basename', 'extension', 'mime_type', 'content', 'content_sha256', 'size_bytes', 'is_deleted', 'status', 'last_opened_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'deleted', 'conflict']
  - constraint: foreign key(vault_id) references vaults(id)
  - constraint: unique(vault_id, path)
  - constraint: size_bytes >= 0
  - constraint: extension != ''
- `sessions.json` — Client sessions for the integration server, tracking which vault/file is active. Tools like get_active_file/delete_active_file/append_active_file operate against the active_file_id in the current session. (12 rows; fields: ['id', 'vault_id', 'active_file_id', 'client_name', 'status', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'expired', 'revoked']
  - constraint: foreign key(vault_id) references vaults(id)
  - constraint: foreign key(active_file_id) references files(id)
  - constraint: status in ('active','expired','revoked')
  - constraint: active_file_id is null or exists(select 1 from files f where f.id = active_file_id and f.vault_id = vault_id and f.status != 'deleted')
- `edit_operations.json` — Append/insert/delete actions performed via the API. Provides an auditable log and supports conflict detection/rollback workflows. (17 rows; fields: ['id', 'vault_id', 'file_id', 'session_id', 'operation_type', 'target_selector', 'payload_text', 'before_sha256', 'after_sha256', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'applied', 'failed', 'cancelled']
  - constraint: foreign key(vault_id) references vaults(id)
  - constraint: foreign key(file_id) references files(id)
  - constraint: foreign key(session_id) references sessions(id)
  - constraint: operation_type in ('open_file','append','insert','delete')
- `search_queries.json` — Persisted search requests and their results for the simple text search tool. Stores query text, scope (vault/dir), and matched file ids with relevance scores. (12 rows; fields: ['id', 'vault_id', 'session_id', 'query_text', 'dir_path', 'status', 'result_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'completed', 'failed']
  - constraint: foreign key(vault_id) references vaults(id)
  - constraint: foreign key(session_id) references sessions(id)
  - constraint: status in ('queued','completed','failed')
  - constraint: result_count >= 0
- `search_results.json` — Results for a search query mapping matched files with ordering and relevance score, enabling deterministic responses. (30 rows; fields: ['id', 'search_query_id', 'file_id', 'rank', 'score', 'snippet', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active']
  - constraint: foreign key(search_query_id) references search_queries(id) on delete cascade
  - constraint: foreign key(file_id) references files(id)
  - constraint: unique(search_query_id, rank)
  - constraint: unique(search_query_id, file_id)

## Business rules enforced by the tools

- get_active_file returns sessions.active_file_id for the caller's active session; the referenced file must have status='available' and is_deleted=false.
- open_file sets sessions.active_file_id to the selected file and writes an edit_operations row with operation_type='open_file' and status='applied'.
- delete_active_file requires sessions.active_file_id is not null; it sets files.status='deleted', files.is_deleted=true, files.content=null, updates files.updated_at, and records an edit_operations row with operation_type='delete'.
- append_active_file requires the active file exists and vault status is 'active' (not 'read_only' or 'disabled'); it appends payload_text to files.content, updates content_sha256/size_bytes, and records an edit_operations row with operation_type='append'.
- insert_active_file and insert_file apply a deterministic modification using edit_operations.target_selector (heading/block_ref/frontmatter). If selector does not resolve uniquely, the operation must end with status='failed' and files.content must remain unchanged.
- insert_file targets a specific files.id (or vault_id+path resolved by server implementation); it must enforce that the target file belongs to the same vault as the session context when session_id is present.
- list_files returns files filtered by vault_id and optional dir_path; it must exclude files with status='deleted' unless explicitly requested by an internal flag (not exposed in current tool surface).
- search_simple creates a search_queries row with query_text and optional dir_path scope, computes matching files where status='available' and content is not null, writes ordered search_results rows, then marks search_queries.status='completed' with result_count set accordingly.
- All mutating operations (append/insert/delete) are rejected when vaults.status in ('read_only','disabled').
- Optimistic concurrency: if a tool supplies before_sha256 (implementation-defined), the server must fail the operation when files.content_sha256 differs, setting files.status='conflict' and operation status='failed'.
- Quota/limits: payload_text length must be <= 200000 characters; query_text length must be 1..4096; operations violating limits must be rejected and logged as failed edit_operations.