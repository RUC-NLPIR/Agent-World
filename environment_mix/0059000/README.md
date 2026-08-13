# FTP Access Server — local MCP environment

This backend stores FTP connection profiles, a virtual filesystem index (directories/files) for remote FTP servers, and an audit log of operations executed through the API. Core workflows: configure a server profile, perform filesystem operations (list/create/upload/download/delete), and record each action with results, byte counts, and errors for traceability and quota enforcement.

Repository: https://github.com/alxspiker/mcp-server-ftp
Homepage: https://smithery.ai/server/@alxspiker/mcp-server-ftp

## Datastore

- `ftp_servers.json` — Configured remote FTP server connection profiles used by tools to execute filesystem operations. (12 rows; fields: ['id', 'name', 'host', 'port', 'username', 'password_ref', 'root_path', 'use_tls', 'passive_mode', 'connect_timeout_seconds', 'read_timeout_seconds', 'status', 'last_healthcheck_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled', 'deleted']
  - constraint: unique(name)
  - constraint: port >= 1 AND port <= 65535
  - constraint: connect_timeout_seconds >= 1 AND connect_timeout_seconds <= 120
  - constraint: read_timeout_seconds >= 1 AND read_timeout_seconds <= 600
- `ftp_directories.json` — Directory nodes in a cached index of the remote FTP filesystem, scoped to a server profile. (17 rows; fields: ['id', 'server_id', 'parent_directory_id', 'path', 'name', 'status', 'last_listed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['present', 'deleting', 'deleted']
  - constraint: fk(server_id) references ftp_servers(id) on delete restrict
  - constraint: fk(parent_directory_id) references ftp_directories(id) on delete restrict
  - constraint: unique(server_id, path)
  - constraint: path LIKE '/%'
- `ftp_files.json` — File nodes in a cached index of the remote FTP filesystem, scoped to a server profile and directory. (19 rows; fields: ['id', 'server_id', 'directory_id', 'path', 'name', 'size_bytes', 'content_type', 'etag', 'status', 'last_seen_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['present', 'uploading', 'deleting', 'deleted']
  - constraint: fk(server_id) references ftp_servers(id) on delete restrict
  - constraint: fk(directory_id) references ftp_directories(id) on delete restrict
  - constraint: unique(server_id, path)
  - constraint: path LIKE '/%'
- `ftp_transfers.json` — Tracks upload/download operations, including progress, byte counts, and storage references for downloaded content handled by the API layer. (19 rows; fields: ['id', 'server_id', 'file_id', 'direction', 'remote_path', 'bytes_total', 'bytes_transferred', 'storage_ref', 'checksum_sha256', 'status', 'error_code', 'error_message', 'started_at', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'in_progress', 'succeeded', 'failed', 'cancelled']
  - constraint: fk(server_id) references ftp_servers(id) on delete restrict
  - constraint: fk(file_id) references ftp_files(id) on delete set null
  - constraint: direction IN ('upload','download')
  - constraint: remote_path LIKE '/%'
- `ftp_operations.json` — Immutable audit log for every tool call (list/create/upload/download/delete) including target paths, outcomes, and linkage to transfers. (20 rows; fields: ['id', 'server_id', 'tool_name', 'target_path', 'directory_id', 'file_id', 'transfer_id', 'request_metadata', 'result_metadata', 'status', 'error_code', 'error_message', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['received', 'running', 'succeeded', 'failed']
  - constraint: fk(server_id) references ftp_servers(id) on delete restrict
  - constraint: fk(directory_id) references ftp_directories(id) on delete set null
  - constraint: fk(file_id) references ftp_files(id) on delete set null
  - constraint: fk(transfer_id) references ftp_transfers(id) on delete set null

## Business rules enforced by the tools

- All filesystem operations must be scoped to an ftp_servers.root_path; any target_path that resolves outside root_path (via .., symlinks where detectable, or absolute paths) must be rejected.
- Tools without explicit parameters default to operating on the server's root_path (for list/create/delete directory where applicable) or on a server-configured default file path; the chosen path must be stored in ftp_operations.target_path.
- list-directory: creates an ftp_operations row, then refreshes/updates ftp_directories.last_listed_at and upserts ftp_directories/ftp_files children for the listed directory; removed remote entries may be marked deleted but not physically removed immediately.
- create-directory: must upsert ftp_directories(server_id,path) with status present; if a record exists in deleted status, it may transition to present after successful remote mkdir.
- delete-directory: cannot transition a directory to deleted if it still has any ftp_files.status != 'deleted' or ftp_directories children with status != 'deleted' (enforce emptiness or require recursive delete at API layer; since no recursive tool exists, enforce empty).
- upload-file: creates ftp_transfers(direction='upload') with status queued, then sets ftp_files.status to uploading for the target path; upon success, ftp_files transitions to present and size_bytes is updated; on failure, ftp_files may transition to deleted only if the remote write is known to be partial/rolled back, otherwise remain present with updated_at set.
- download-file: creates ftp_transfers(direction='download') and writes downloaded content to internal storage referenced by storage_ref; the operation result_metadata must include storage_ref and bytes_transferred.
- delete-file: transitions ftp_files.status from present to deleting to deleted only after remote deletion succeeds; if remote deletion fails with not-found, mark deleted but record error_code='NOT_FOUND' and treat as succeeded for idempotency.
- ftp_servers.status='disabled' forbids new ftp_operations except list-directory (optional) and must fail upload/download/delete/create with error_code='SERVER_DISABLED'.
- FK integrity: a ftp_files.directory_id must belong to the same server_id as ftp_files.server_id; similarly ftp_directories.parent_directory_id must share the same server_id (enforced via application-level check or composite foreign keys).
- Operational audit: every tool invocation must create exactly one ftp_operations record and transition it to succeeded or failed; failures must populate error_code and error_message.
- Quotas/safety limits: per operation, bytes_total (if known) must be <= 10737418240 (10 GiB) and list-directory result entries count recorded in result_metadata must be <= 100000; otherwise fail with error_code='LIMIT_EXCEEDED'.