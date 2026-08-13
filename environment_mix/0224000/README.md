# Trello — local MCP environment

This backend stores Trello-like boards with lists and cards, plus card membership assignments and an append-only activity log to power recent activity feeds. Core workflows are: read lists/cards from the configured board, create/update/move/archive cards and lists, manage card members, and query cards assigned to the authenticated user.

Repository: https://github.com/Hint-Services/mcp-trello
Homepage: https://smithery.ai/server/@Hint-Services/mcp-trello

## Datastore

- `boards.json` — Workspace-scoped Trello boards. The MCP server is typically configured to operate against one board, but the backend supports multiple boards. (12 rows; fields: ['id', 'name', 'description', 'status', 'default', 'created_by_member_id', 'created_at', 'updated_at', 'closed_at'])
  - lifecycle `status`: ['active', 'closed']
  - constraint: unique(name) where status = 'active'
  - constraint: unique(default) where default = true
  - constraint: created_at <= updated_at
- `members.json` — Trello members/users who can be assigned to cards and appear in activity events. Includes the authenticated user used by getMyCards. (12 rows; fields: ['id', 'username', 'full_name', 'email', 'is_authenticated_user', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'disabled']
  - constraint: unique(username)
  - constraint: unique(is_authenticated_user) where is_authenticated_user = true
- `lists.json` — Lists belonging to a board. Used by getLists, addList, archiveList, and as a container for cards. (20 rows; fields: ['id', 'board_id', 'name', 'position', 'status', 'archived_at', 'created_by_member_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: unique(board_id, name) where status = 'active'
  - constraint: position >= 0
  - constraint: created_at <= updated_at
  - constraint: FK(board_id) references boards(id) on delete restrict
- `cards.json` — Cards on lists. Supports addCard, updateCard, moveCard, archiveCard, getCardsByList, and getMyCards (via card_members). (33 rows; fields: ['id', 'board_id', 'list_id', 'title', 'description', 'position', 'due_at', 'status', 'archived_at', 'created_by_member_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived']
  - constraint: position >= 0
  - constraint: created_at <= updated_at
  - constraint: FK(board_id) references boards(id) on delete restrict
  - constraint: FK(list_id) references lists(id) on delete restrict
- `card_members.json` — Join table mapping members assigned to cards. Powers changeCardMembers and getMyCards. (30 rows; fields: ['id', 'card_id', 'member_id', 'assigned_by_member_id', 'status', 'created_at', 'updated_at', 'removed_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: unique(card_id, member_id) where status = 'active'
  - constraint: FK(card_id) references cards(id) on delete cascade
  - constraint: FK(member_id) references members(id) on delete restrict
  - constraint: status = 'removed' implies removed_at is not null
- `activity_events.json` — Append-only activity feed for boards (card/list create/update/move/archive, membership changes). Used by getRecentActivity. (35 rows; fields: ['id', 'board_id', 'actor_member_id', 'event_type', 'list_id', 'card_id', 'payload', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['list.created', 'list.archived', 'card.created', 'card.updated', 'card.moved', 'card.archived', 'card.members.changed']
  - constraint: FK(board_id) references boards(id) on delete cascade
  - constraint: FK(actor_member_id) references members(id) on delete restrict
  - constraint: card_id is not null for event_type in ('card.created','card.updated','card.moved','card.archived','card.members.changed')
  - constraint: list_id is not null for event_type in ('list.created','list.archived')

## Business rules enforced by the tools

- All tools operate against boards.default = true unless an internal override is provided by server configuration.
- getLists returns lists where board_id = default_board.id and status = 'active', ordered by position ascending.
- addList inserts a lists row with board_id = default_board.id, status = 'active', position = max(position)+1 (or 0 if none), and writes an activity_events row of type 'list.created'.
- archiveList transitions lists.status from 'active' to 'archived', sets archived_at, and writes an activity_events row of type 'list.archived'. Archiving a list does not delete its cards; cards remain but getCardsByList should not return cards for archived lists unless explicitly implemented (this MCP surface does not expose that toggle).
- getCardsByList returns cards for each active list on the default board grouped by list_id (implementation may return as a flat list with list_id present), filtered to cards.status = 'active', ordered by list.position then card.position.
- addCard inserts a cards row in a specified list (must be lists.status='active' and lists.board_id=default board), status='active', position=max(position)+1 within the list, and writes an activity_events row of type 'card.created'.
- updateCard updates mutable fields on cards (title, description, due_at, position) only when cards.status='active'. It writes an activity_events row of type 'card.updated' capturing changed fields in payload.
- moveCard changes cards.list_id and optionally position; the destination list must be active and on the same board. It writes an activity_events row of type 'card.moved' with payload including from_list_id and to_list_id.
- archiveCard transitions cards.status from 'active' to 'archived', sets archived_at, and writes an activity_events row of type 'card.archived'. Archived cards are excluded from getCardsByList and getMyCards.
- changeCardMembers results in card_members rows matching the desired member set: add missing assignments as status='active', mark removed ones as status='removed' with removed_at, and write an activity_events row of type 'card.members.changed' with payload listing added_member_ids and removed_member_ids. It must not create duplicate active assignments due to unique(card_id, member_id) where status='active'.
- getMyCards returns cards where cards.status='active' AND exists an active card_members row with member_id = members.id where members.is_authenticated_user = true, restricted to the default board.
- getRecentActivity returns activity_events for default board ordered by created_at desc, limited by a server-side default (e.g., 50) if the tool does not accept a limit parameter.
- FK integrity is enforced: cards.list_id must reference an existing list, and cards.board_id must equal lists.board_id; card_members.card_id must reference an existing card.
- Status transitions are enforced exactly as declared; archived entities cannot be updated or moved except via internal admin operations not present in this tool surface.