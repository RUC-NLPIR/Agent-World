# Miro Server — local MCP environment

This backend stores Miro organizations/teams/projects, boards, board content items (multiple item types with shared geometry/style), board membership/sharing, grouping and tagging, plus enterprise-only governance data like classifications, audit logs, exports, eDiscovery cases/legal holds, and board content change logs. The main workflows are CRUD on boards and items (including bulk and file-backed image updates), managing relationships (connectors, groups, tags, members), and running long-lived enterprise jobs (exports) with auditable events and retention limits.

Repository: https://github.com/k-jarzyna/mcp-miro
Homepage: https://smithery.ai/server/@k-jarzyna/mcp-miro

## Datastore

- `principals.json` — Represents users, teams, organizations, and projects as shareable/ownable principals. Used for membership, access control, and enterprise org features. (21 rows; fields: ['id', 'principal_type', 'parent_principal_id', 'external_miro_id', 'display_name', 'email', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: display_name is required
  - constraint: principal_type in ('user','team','organization','project')
  - constraint: email is NOT NULL only when principal_type='user'
  - constraint: unique(external_miro_id, principal_type) where external_miro_id IS NOT NULL
- `boards.json` — Miro boards plus enterprise-only metadata such as classification and soft deletion/trash state. (19 rows; fields: ['id', 'external_miro_board_id', 'organization_id', 'team_id', 'project_id', 'name', 'description', 'sharing_policy', 'status', 'trashed_at', 'purge_after', 'classification', 'created_by_user_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'trashed', 'deleted']
  - constraint: name is required
  - constraint: organization_id/team_id/project_id must reference matching principal_type when set
  - constraint: unique(external_miro_board_id) where external_miro_board_id IS NOT NULL
  - constraint: status='trashed' implies trashed_at IS NOT NULL
- `board_memberships.json` — Board sharing and membership: who can access a board, with what role, and invitation lifecycle. Drives share-board, get-all-board-members, update/remove member, and enterprise project membership operations via principal hierarchy. (18 rows; fields: ['id', 'board_id', 'member_principal_id', 'role', 'status', 'invited_by_user_id', 'team_assignment_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['invited', 'active', 'removed']
  - constraint: unique(board_id, member_principal_id) where status != 'removed'
  - constraint: role in ('owner','editor','commenter','viewer')
  - constraint: board_id references boards.id
  - constraint: member_principal_id references principals.id
- `board_objects.json` — Unified storage for all board content objects: items (cards, sticky notes, frames, docs, text, images, shapes, embeds, app cards, mindmap nodes), connectors, groups, and tags. Supports CRUD, bulk creates, positioning/parenting, grouping, tagging, connectors, classification-related content logs, and eDiscovery hold item referencing. (19 rows; fields: ['id', 'external_miro_object_id', 'board_id', 'object_type', 'status', 'parent_object_id', 'group_id', 'title', 'text_content', 'data', 'style', 'geometry', 'connector_from_object_id', 'connector_to_object_id', 'image_source_url', 'image_asset_ref', 'created_by_user_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: board_id references boards.id
  - constraint: unique(external_miro_object_id, board_id) where external_miro_object_id IS NOT NULL
  - constraint: object_type='connector' implies connector_from_object_id IS NOT NULL and connector_to_object_id IS NOT NULL
  - constraint: object_type!='connector' implies connector_from_object_id IS NULL and connector_to_object_id IS NULL
- `object_links.json` — Many-to-many relationships between board_objects: tagging (tag<->item) and group membership (group<->item) with ordering. Used by attach-tag/detach-tag/get-item-tags and get-group-items/update-group/ungroup-items. (18 rows; fields: ['id', 'board_id', 'link_type', 'from_object_id', 'to_object_id', 'position_index', 'created_at', 'updated_at'])
  - lifecycle `link_type`: ['tag_attachment', 'group_membership']
  - constraint: unique(board_id, link_type, from_object_id, to_object_id)
  - constraint: from_object_id references board_objects.id and must have same board_id
  - constraint: to_object_id references board_objects.id and must have same board_id
  - constraint: link_type='tag_attachment' implies from_object_id refers to object_type='tag' and to_object_id refers to object_type LIKE 'item_%'
- `enterprise_ops.json` — Enterprise-only operational records: audit log events, board export jobs & results, eDiscovery cases and legal holds, and board content change logs. Modeled as an operation/event store with typed payloads and retention control (90 days for audit logs). (19 rows; fields: ['id', 'record_type', 'organization_id', 'board_id', 'case_id', 'legal_hold_id', 'object_id', 'status', 'payload', 'occurred_at', 'expires_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['immutable', 'queued', 'running', 'succeeded', 'failed', 'open', 'closed', 'active', 'released']
  - constraint: organization_id references principals.id where principal_type='organization'
  - constraint: record_type='audit_event' implies status='immutable' and occurred_at IS NOT NULL and expires_at IS NOT NULL
  - constraint: record_type='board_export_job' implies status in ('queued','running','succeeded','failed')
  - constraint: record_type='board_export_result' implies status='immutable' and payload contains downloadable artifact references

## Business rules enforced by the tools

- list-boards returns boards where status='active' for the caller's accessible memberships; trashed boards are excluded unless an internal admin flag is used.
- delete-board sets boards.status to 'trashed' and sets trashed_at; hard deletion to 'deleted' is only allowed by privileged operations or after purge_after.
- copy-board creates a new boards row with new external_miro_board_id and duplicates board_objects (excluding deleted) and object_links, remapping IDs; connectors must be remapped to the copied object IDs.
- get-items-on-board returns board_objects where board_id matches, object_type LIKE 'item_%' and status='active'.
- get-connectors returns board_objects where board_id matches, object_type='connector' and status='active'.
- update-item-position may only change geometry and/or parent_object_id within the same board; parent_object_id must refer to an object that can contain items (e.g., frame) as enforced by application logic on object_type.
- create-items-in-bulk and create-items-in-bulk-using-file must be atomic per request: either all created objects persist or none (transactional).
- create-image-item-using-file and update-image-item-using-file must store image_asset_ref and must not store image_source_url for that object; create-image-item-using-url must store image_source_url.
- delete-item/delete-connector/delete-*-item operations soft-delete by setting board_objects.status='deleted'; object_links referencing deleted objects must be removed or ignored in reads.
- attach-tag creates an object_links row of link_type='tag_attachment' where from_object_id is a 'tag' object and to_object_id is an item on the same board; duplicates are rejected by uniqueness constraint.
- update-group replaces group membership links for that group (object_links where link_type='group_membership' and from_object_id=group_id) with the provided set; ungroup-items deletes those links without deleting the items.
- get-all-board-members reads board_memberships where board_id matches and status in ('invited','active'); remove-board-member transitions status to 'removed' and preserves history.
- update-board-member can change role only when membership status='active'; cannot remove or downgrade the last remaining active owner.
- share-board creates or updates board_memberships rows and sets status to 'invited' or 'active' depending on invite flow; team_assignment_id must be a team principal under the board's organization if present.
- Enterprise-only tools require the board.organization_id to be non-null and the requesting principal to be in that organization; otherwise reject.
- get-audit-logs returns enterprise_ops records where record_type='audit_event', organization_id matches, occurred_at within last 90 days, and expires_at > now.
- create-board-export-job creates enterprise_ops record_type='board_export_job' with status='queued' and payload listing board IDs; subsequent status polling reads and updates status; results are stored as record_type='board_export_result' linked via payload (job_id) or board_id.
- get-board-content-logs returns enterprise_ops where record_type='board_content_log' and board_id matches, ordered by occurred_at descending.
- eDiscovery: get-all-cases/get-case reads enterprise_ops record_type='ediscovery_case'; legal holds are enterprise_ops record_type='legal_hold' referencing case_id; legal hold content items are enterprise_ops record_type='legal_hold_content_item' referencing legal_hold_id and pointing to board_id/object_id.