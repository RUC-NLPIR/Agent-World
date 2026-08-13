# File Context Server — local MCP environment

This backend stores repository file inventory, content snapshots, and derived artifacts (chunked context payloads and code outlines) used by the File Context Server tools. Workflows include scanning/refreshing a repository index, serving chunked reads for files/directories with filters, switching an active profile that defines context selection rules, and generating/returning outlines for supported source files.

Repository: https://github.com/bsmi021/mcp-file-context-server
Homepage: https://smithery.ai/server/@bsmi021/mcp-file-context-server

## Datastore

- `repositories.json` — A local workspace/repository root that the server can read from. All file paths are stored relative to repo_root to prevent path traversal and to support caching across tool calls. (12 rows; fields: ['id', 'name', 'repo_root', 'active_profile_id', 'status', 'last_scan_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'missing']
  - constraint: unique(repo_root)
  - constraint: name <> ''
  - constraint: repo_root <> ''
  - constraint: active_profile_id references profiles.id on update set null on delete set null
- `repo_files.json` — Inventory of files discovered under a repository root, excluding ignored artifacts. Stores metadata needed for filtering, chunking decisions, and caching outlines/context snapshots. (32 rows; fields: ['id', 'repository_id', 'relative_path', 'is_directory', 'extension', 'size_bytes', 'mtime', 'content_sha256', 'ignored_reason', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['indexed', 'missing', 'ignored', 'error']
  - constraint: unique(repository_id, relative_path)
  - constraint: relative_path <> ''
  - constraint: size_bytes is null when is_directory = true
  - constraint: size_bytes >= 0 when is_directory = false
- `profiles.json` — Context-generation profiles that define which files are included/excluded and chunking defaults for get_profile_context. set_profile selects the active one per repository. (12 rows; fields: ['id', 'repository_id', 'name', 'description', 'include_globs', 'exclude_globs', 'include_extensions', 'recursive_default', 'max_size_default_bytes', 'encoding_default', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(repository_id, name)
  - constraint: name <> ''
  - constraint: max_size_default_bytes >= 1024
  - constraint: max_size_default_bytes <= 104857600
- `context_requests.json` — A normalized record of read_context/get_chunk_count/get_profile_context requests, including parameters and computed chunk counts. Supports caching and reproducibility across calls. (31 rows; fields: ['id', 'repository_id', 'profile_id', 'request_type', 'path', 'max_size_bytes', 'encoding', 'recursive', 'file_types', 'refresh', 'chunk_count', 'selection_fingerprint', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'materializing', 'ready', 'error']
  - constraint: path <> ''
  - constraint: max_size_bytes >= 1024
  - constraint: max_size_bytes <= 104857600
  - constraint: chunk_count is null or chunk_count >= 0
- `context_chunks.json` — Materialized chunk payloads for context requests. Used by read_context (chunkNumber) and to support get_chunk_count via context_requests.chunk_count. (39 rows; fields: ['id', 'context_request_id', 'chunk_number', 'byte_count', 'payload', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ready', 'stale', 'error']
  - constraint: unique(context_request_id, chunk_number)
  - constraint: chunk_number >= 0
  - constraint: byte_count >= 0
  - constraint: context_request_id references context_requests.id on delete cascade
- `code_outlines.json` — Cached outlines generated for supported source files (TypeScript/JavaScript/Python). generate_outline reads/writes these records keyed by file hash + parser version. (34 rows; fields: ['id', 'repository_id', 'repo_file_id', 'relative_path', 'language', 'parser_version', 'content_sha256', 'outline', 'status', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ready', 'stale', 'error']
  - constraint: unique(repository_id, repo_file_id, parser_version, content_sha256)
  - constraint: unique(repository_id, relative_path, parser_version, content_sha256)
  - constraint: relative_path <> ''
  - constraint: parser_version <> ''

## Business rules enforced by the tools

- All tool 'path' inputs must be normalized and resolved under repositories.repo_root; requests attempting path traversal (e.g., '..' escaping root) must be rejected.
- Default ignore rules (e.g., .git/, node_modules/, dist/, __pycache__/, .venv/, IDE folders, and known artifact files like *.pyc) must be applied during repo_files inventory and during context selection; ignored files must have repo_files.status='ignored' and ignored_reason populated.
- get_chunk_count must compute (or reuse) context_requests.chunk_count for an equivalent parameter set (repository_id, path, max_size_bytes, encoding, recursive, file_types, profile_id, refresh) and return it without requiring context_chunks to be fetched.
- read_context must return the context_chunks row where context_request_id matches the resolved request and chunk_number equals chunkNumber; if chunkNumber < 0 or chunkNumber >= chunk_count it must error.
- For requests where selected file set or any selected file mtime/content_sha256 changes, context_chunks for the prior selection_fingerprint must be marked status='stale' and a new context_request must be materialized.
- set_profile(profile_name) must set repositories.active_profile_id to the matching profiles.id within the same repository where profiles.status='active'; if no match exists it must error.
- get_profile_context(refresh=false) must use repositories.active_profile_id and its defaults (recursive_default, max_size_default_bytes, encoding_default, include_extensions/exclude_globs/include_globs) to create or reuse a ready context_requests row with request_type='get_profile_context'. If refresh=true it must rescan file selection (updating repo_files as needed) and produce a new selection_fingerprint.
- generate_outline(path) must only succeed for files whose extension implies supported languages (py/js/ts/tsx/jsx) and must map to code_outlines.language accordingly; unsupported types must error.
- generate_outline must reuse an existing code_outlines row with status='ready' when repo_files.content_sha256 and parser_version match; otherwise it must create/update a row and mark prior ones for the same repo_file_id and parser_version as status='stale'.
- repo_files.unique(repository_id, relative_path) must be maintained by upsert during scans; files removed from disk must transition to status='missing' (not deleted) to preserve caching lineage and auditability.
- All maxSize parameters must be enforced within [1024, 104857600]; encoding must be one of the allowed encodings; fileTypes must be normalized to lowercase strings without leading dots.