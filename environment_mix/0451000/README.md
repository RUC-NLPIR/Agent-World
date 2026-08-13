# Text Editor MCP Server — local MCP environment

This backend stores a persistent, server-side text editing workspace that can view directories/files, create new files, apply deterministic edits (string replace and line insert), and support undo across calls. The core workflow is: a client issues an edit command against an absolute path; the server records the operation, applies it to the latest file snapshot, and can revert by undoing the most recent edit operation for that file.

Repository: https://github.com/bhouston/mcp-server-text-editor
Homepage: https://smithery.ai/server/@bhouston/mcp-server-text-editor

## Datastore

- `projects.json` — Top-level workspace/root for a repository or filesystem subtree served by the MCP text editor. Paths supplied to the tool are validated to be within a configured project root. (12 rows; fields: ['id', 'name', 'root_path', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'readonly', 'disabled']
  - constraint: unique(root_path)
  - constraint: length(name) between 1 and 120
  - constraint: root_path like '/%'
- `fs_nodes.json` — Canonical representation of files and directories within a project. Directories are used for view operations on folder paths; files are edited and versioned via snapshots. (32 rows; fields: ['id', 'project_id', 'path', 'node_type', 'status', 'current_snapshot_id', 'byte_size', 'line_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['present', 'deleted']
  - constraint: unique(project_id, path)
  - constraint: path like '/%'
  - constraint: byte_size is null or byte_size >= 0
  - constraint: line_count is null or line_count >= 0
- `file_snapshots.json` — Immutable content snapshots for files. Each edit produces a new snapshot, enabling view-by-range against the current snapshot and undo by rolling back to a previous snapshot. (29 rows; fields: ['id', 'node_id', 'parent_snapshot_id', 'content_text', 'content_sha256', 'byte_size', 'line_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active']
  - constraint: byte_size >= 0
  - constraint: line_count >= 0
  - constraint: length(content_sha256) = 64
  - constraint: unique(node_id, content_sha256)
- `edit_operations.json` — Append-only audit log of all text_editor tool calls. Used to implement undo and to enforce command-specific parameter requirements and server-side validation outcomes. (40 rows; fields: ['id', 'project_id', 'node_id', 'command', 'path', 'description', 'file_text', 'old_str', 'new_str', 'insert_line', 'view_range', 'pre_snapshot_id', 'post_snapshot_id', 'status', 'error_code', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['applied', 'no_change', 'failed']
  - constraint: length(description) between 1 and 80
  - constraint: path like '/%'
  - constraint: command in ('view','create','str_replace','insert','undo_edit')
  - constraint: status in ('applied','no_change','failed')
- `undo_pointers.json` — Tracks the last undoable operation per file to implement undo_edit deterministically (stack-like behavior) across stateless tool calls. (32 rows; fields: ['id', 'node_id', 'latest_edit_operation_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['available', 'empty']
  - constraint: unique(node_id)
  - constraint: status='empty' implies latest_edit_operation_id is null

## Business rules enforced by the tools

- Every text_editor call must create exactly one edit_operations row with command, path, and description populated; description length must be 1..80 characters.
- The server must map the tool parameter `path` to fs_nodes.path within an active project and reject any path not under projects.root_path with error_code=PATH_OUT_OF_ROOT.
- For command=view: if path refers to a directory node_type=directory, the response is derived from fs_nodes rows under that prefix; if it refers to a file, the response is derived from fs_nodes.current_snapshot_id and file_snapshots.content_text; view_range must be either null or a 2-element array [start,end] where start>=1 and (end=-1 or end>=start).
- For command=create: the target path must not already exist as a present fs_nodes row; on success create fs_nodes(node_type='file', status='present') and a file_snapshots row; set fs_nodes.current_snapshot_id to the new snapshot; record pre_snapshot_id=null and post_snapshot_id=new snapshot in edit_operations.
- For command=str_replace: path must resolve to a present file node; old_str must be provided and must occur in the current snapshot content; if old_str occurs more than once the operation must fail with error_code=OLD_STR_NOT_UNIQUE; if it occurs zero times fail with error_code=OLD_STR_NOT_FOUND; on success create a new snapshot and update fs_nodes.current_snapshot_id.
- For command=insert: path must resolve to a present file node; insert_line must be an integer >=1 and <= current line_count (inserting after the last line is allowed by using insert_line=line_count); new_str must be provided; on success create a new snapshot and update fs_nodes.current_snapshot_id.
- For command=undo_edit: path must resolve to a present file node; if undo_pointers.status='empty' then the operation must be recorded as no_change; otherwise the server must revert fs_nodes.current_snapshot_id from the latest_edit_operation.post_snapshot_id back to latest_edit_operation.pre_snapshot_id (or delete the node if the latest operation was create and pre_snapshot_id is null), then update undo_pointers to the previous edit operation in the chain.
- Projects with status=readonly must reject mutating commands (create/str_replace/insert/undo_edit) with error_code=PROJECT_READONLY while still allowing view.
- FK integrity must be enforced: fs_nodes.project_id must exist; file_snapshots.node_id must refer to a file fs_nodes row; edit_operations.project_id must exist; edit_operations.node_id if present must exist; snapshot references must exist when set.
- fs_nodes.node_type='directory' must never have current_snapshot_id set; only file nodes may have snapshots.
- For successful mutating operations, edit_operations.status must be applied and post_snapshot_id must be non-null; for view operations, post_snapshot_id must be null.