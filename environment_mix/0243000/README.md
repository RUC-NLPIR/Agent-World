# Trello MCP Server — local MCP environment

This backend stores a local mirror of a user's Trello workspace needed to serve an MCP tool surface: boards, lists, cards, and card checklists with items. The main workflows are reading entities by id and parent (boards->lists->cards, cards->checklists->items) and mutating them (create/update/archive/delete) while preserving ordering (pos) and lifecycle states (open/archived/deleted).

Repository: https://github.com/m0xai/trello-mcp-server
Homepage: https://smithery.ai/server/@m0xai/trello-mcp-server

## Datastore

- `trello_boards.json` — Boards accessible to the authenticated Trello user; used to list boards and resolve board metadata for downstream list/card operations. (12 rows; fields: ['id', 'trello_id', 'name', 'desc', 'url', 'closed', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(trello_id)
  - constraint: name <> ''
  - constraint: closed = true implies status in ('archived','deleted') OR closed = false implies status='active'
- `trello_lists.json` — Lists within boards; supports listing lists for a board and creating/updating/archiving lists. Also acts as the parent container for cards. (24 rows; fields: ['id', 'trello_id', 'board_id', 'name', 'pos', 'closed', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'archived', 'deleted']
  - constraint: unique(trello_id)
  - constraint: foreign key(board_id) references trello_boards(id) on delete restrict
  - constraint: name <> ''
  - constraint: pos >= 0
- `trello_cards.json` — Cards within lists; supports listing cards by list, reading by id, and create/update/delete operations. (33 rows; fields: ['id', 'trello_id', 'list_id', 'name', 'desc', 'pos', 'due_at', 'closed', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'archived', 'deleted']
  - constraint: unique(trello_id)
  - constraint: foreign key(list_id) references trello_lists(id) on delete restrict
  - constraint: name <> ''
  - constraint: pos >= 0
- `trello_checklists.json` — Checklists attached to cards; supports reading a checklist by id, listing a card's checklists, and creating/updating/deleting checklists. (31 rows; fields: ['id', 'trello_id', 'card_id', 'name', 'pos', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(trello_id)
  - constraint: foreign key(card_id) references trello_cards(id) on delete restrict
  - constraint: name <> ''
  - constraint: pos >= 0
- `trello_checkitems.json` — Items within a checklist; supports adding/updating/deleting checkitems with checked state and ordering. (31 rows; fields: ['id', 'trello_id', 'checklist_id', 'name', 'checked', 'pos', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(trello_id)
  - constraint: foreign key(checklist_id) references trello_checklists(id) on delete restrict
  - constraint: name <> ''
  - constraint: pos >= 0

## Business rules enforced by the tools

- get_boards returns all trello_boards where status <> 'deleted' ordered by updated_at desc (or name asc) for the authenticated user context (not modeled here because the tool surface does not expose auth parameters).
- get_board returns a single board; if multiple boards exist and no id parameter is provided by the tool surface, the server must choose a deterministic default (e.g., most recently updated active board) and log the selection.
- get_lists requires a board_id; the implementation must resolve either a local board id (trl_brd_...) or a Trello trello_id and return lists where board_id matches and status <> 'deleted' ordered by pos asc.
- create_list requires board_id and name (despite the JSON schema showing no properties); the implementation must reject empty names and must map pos input ('top'|'bottom'|numeric-string) to a numeric pos. If omitted, pos defaults to bottom (max(pos)+1).
- update_list requires list_id and name; name must be non-empty and unique within the board among non-deleted lists (unique(board_id,name) where status<>'deleted').
- delete_list archives a list: it must set trello_lists.closed=true and status='archived' (not hard-delete) unless the backing Trello API reports a hard delete; in that case status='deleted'.
- get_cards requires list_id and returns cards where list_id matches and status <> 'deleted' ordered by pos asc.
- create_card requires list_id and name; desc may be null. Newly created cards default to status='open', closed=false, and pos=max(pos)+1 within the list unless Trello returns an explicit pos.
- update_card may change name/desc/due_at/pos/list_id/closed; if closed becomes true then status must transition to 'archived'. If list_id changes, the destination list must exist and not be deleted.
- delete_card marks a card as status='deleted' (and may also set closed=true). Deleting a card must not physically delete related checklists/checkitems; they remain but should be treated as inaccessible via parent traversal if the parent card is deleted.
- get_card_checklists requires card_id and returns checklists where card_id matches and status='active' ordered by pos asc.
- create_checklist requires card_id and name; pos can be 'top'|'bottom'|numeric-string and is stored as numeric. Name must be unique per card among active checklists.
- update_checklist may change name and/or pos; if name is provided it must be non-empty and keep uniqueness per card among active checklists.
- delete_checklist sets trello_checklists.status='deleted'. All its checkitems remain but must be treated as non-operable (updates/additions rejected) once the checklist is deleted.
- add_checkitem requires checklist_id, name, checked, and optional pos; pos must map to numeric, checked defaults to false if omitted by client implementation. The checklist must be active.
- update_checkitem requires checklist_id and checkitem_id; updates may include name, checked, pos. The checkitem must belong to the given checklist_id, and both checklist and item must be active.
- delete_checkitem requires checklist_id and checkitem_id; it must verify ownership (checkitem.checklist_id == checklist_id) then set status='deleted'.
- FK integrity must be enforced: lists cannot reference missing boards; cards cannot reference missing lists; checklists cannot reference missing cards; checkitems cannot reference missing checklists.
- Position (pos) values must be >= 0 across lists/cards/checklists/checkitems; when 'top' is requested, set pos to (min(pos)-1) but not below 0; if min(pos)=0 then use a small fractional position (e.g., 0.5) to preserve ordering without violating pos >= 0.