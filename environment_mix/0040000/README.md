# Figma MCP Server — local MCP environment

This backend stores connections to Figma files, cached node thumbnails, and a local mirror of comment threads to support reading and posting comments through the MCP tools. The main workflows are: registering a Figma file into the server, retrieving a node thumbnail (optionally cached), listing comments for a file, and creating comments/replies against nodes while recording sync state with Figma.

Repository: https://github.com/MatthewDailey/figma-mcp
Homepage: https://smithery.ai/server/@MatthewDailey/figma-mcp

## Datastore

- `workspaces.json` — Tenant boundary for the MCP server (e.g., per user/team installation). Owns Figma auth configuration, registered files, and usage limits. (18 rows; fields: ['id', 'name', 'status', 'figma_access_token_ciphertext', 'figma_token_last_rotated_at', 'quota_daily_requests', 'quota_daily_comment_posts', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: quota_daily_requests between 0 and 100000
  - constraint: quota_daily_comment_posts between 0 and 10000
  - constraint: status in ('active','suspended','deleted')
- `figma_files.json` — Figma files registered with the server via add_figma_file. Used as the parent for thumbnails and comments sync. (19 rows; fields: ['id', 'workspace_id', 'figma_file_key', 'name', 'thumbnail_url', 'last_fetched_at', 'comments_last_synced_at', 'status', 'last_error_code', 'last_error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'error', 'deleted']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: unique(workspace_id, figma_file_key)
  - constraint: status in ('active','archived','error','deleted')
  - constraint: figma_file_key length between 1 and 128
- `figma_nodes.json` — Nodes within a Figma file that have been accessed (e.g., via view_node) and/or are referenced by comments. Stores cached thumbnails per node. (18 rows; fields: ['id', 'file_id', 'figma_node_id', 'name', 'thumbnail_url', 'thumbnail_fetched_at', 'thumbnail_ttl_seconds', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'stale', 'deleted']
  - constraint: fk(file_id) references figma_files(id) on delete cascade
  - constraint: unique(file_id, figma_node_id)
  - constraint: thumbnail_ttl_seconds between 60 and 604800
- `figma_comments.json` — Local mirror of comments and replies for a Figma file, including comments created via post_comment and reply_to_comment. Supports read_comments and thread reconstruction. (17 rows; fields: ['id', 'file_id', 'node_id', 'figma_node_id', 'parent_comment_id', 'figma_comment_id', 'message', 'author_display_name', 'author_figma_user_id', 'figma_created_at', 'resolved', 'sync_status', 'last_sync_error', 'created_via', 'created_at', 'updated_at'])
  - lifecycle `sync_status`: ['synced', 'pending_post', 'post_failed', 'tombstoned']
  - constraint: fk(file_id) references figma_files(id) on delete cascade
  - constraint: fk(node_id) references figma_nodes(id) on delete set null
  - constraint: fk(parent_comment_id) references figma_comments(id) on delete cascade
  - constraint: unique(file_id, figma_comment_id) where figma_comment_id is not null
- `api_requests.json` — Request log for MCP tool calls and downstream Figma API calls. Used for rate limiting, quota enforcement, debugging, and auditability. (19 rows; fields: ['id', 'workspace_id', 'tool_name', 'figma_file_id', 'request_params', 'downstream_endpoint', 'downstream_status_code', 'status', 'error_message', 'duration_ms', 'created_at', 'updated_at'])
  - lifecycle `status`: ['ok', 'error', 'rate_limited']
  - constraint: fk(workspace_id) references workspaces(id) on delete cascade
  - constraint: fk(figma_file_id) references figma_files(id) on delete set null
  - constraint: duration_ms is null OR duration_ms >= 0
  - constraint: downstream_status_code is null OR downstream_status_code between 100 and 599

## Business rules enforced by the tools

- All tools must execute within a workspace context; if workspace.status != 'active', mutating tools (add_figma_file, post_comment, reply_to_comment) must be rejected.
- add_figma_file must create (or upsert) a figma_files row unique by (workspace_id, figma_file_key); on upsert it must not change workspace_id.
- view_node must resolve a figma_files record (by figma_file_key) and then upsert a figma_nodes row unique by (file_id, figma_node_id); it may return a cached thumbnail_url if thumbnail_fetched_at + thumbnail_ttl_seconds > now().
- read_comments must return comments for a given file_id/figma_file_key; it should prefer local mirror when comments_last_synced_at is recent, otherwise it must sync from Figma and upsert figma_comments by (file_id, figma_comment_id).
- post_comment must create a top-level figma_comments row with parent_comment_id = null, created_via='mcp_post_comment', sync_status='pending_post', then attempt to post to Figma; on success set sync_status='synced' and fill figma_comment_id and figma_created_at; on failure set sync_status='post_failed' and record last_sync_error.
- reply_to_comment must create a figma_comments row with parent_comment_id pointing to an existing top-level comment in the same file; it must enforce that the parent is not itself a reply.
- When a comment references a Figma node id, the system must store it in figma_comments.figma_node_id; if a figma_nodes record exists for that (file_id, figma_node_id), it should populate figma_comments.node_id for faster joins.
- Quota enforcement: per workspace per UTC day, the count of api_requests for tool calls plus downstream calls must be <= quota_daily_requests; the count of successful post_comment + reply_to_comment attempts must be <= quota_daily_comment_posts; excess must be recorded as api_requests.status='rate_limited' and rejected.
- FK integrity: deleting a figma_files row must cascade delete figma_nodes and figma_comments; deleting a parent comment must cascade delete its replies.
- Uniqueness: a non-null figma_comment_id must be unique within a file; if Figma returns a duplicate, the server must merge by updating the existing row rather than inserting a new one.
- Status transitions must follow declared lifecycles; direct transitions not listed must be rejected (e.g., figma_comments.sync_status cannot move from 'synced' back to 'pending_post').