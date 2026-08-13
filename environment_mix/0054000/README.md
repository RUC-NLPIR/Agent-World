# Claude Server — local MCP environment

This backend stores contextual knowledge snippets for Claude Server, scoped either to a project or to a conversation session. It supports saving contexts with parent/continuation relationships, tagging, cross-references between contexts, and retrieving or listing contexts with simple filters.

Repository: https://github.com/davidteren/claude-server
Homepage: https://smithery.ai/server/@davidteren/claude-server

## Datastore

- `projects.json` — Projects that own project-scoped contexts. Projects are referenced by project contexts and provide a stable namespace for context ids and listing filters. (12 rows; fields: ['id', 'name', 'description', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: unique(name)
  - constraint: status in ('active','archived','deleted')
- `conversation_sessions.json` — Conversation sessions that own conversation-scoped contexts. Sessions are referenced by conversation contexts and provide a stable namespace for context ids and listing filters. (12 rows; fields: ['id', 'title', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'closed', 'deleted']
  - constraint: status in ('active','closed','deleted')
- `contexts.json` — Core stored context objects. A context is either project-scoped or conversation-scoped, contains content, optional metadata, and supports a single parent/continuation pointer depending on type. (18 rows; fields: ['id', 'type', 'project_id', 'session_id', 'content', 'parent_context_id', 'continuation_of_context_id', 'metadata', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(id)
  - constraint: type in ('project','conversation')
  - constraint: content != ''
  - constraint: ((type='project') = (project_id is not null))
- `context_tags.json` — Normalized tags for contexts to support list_contexts(tag=...) and structured tag management. (18 rows; fields: ['id', 'context_id', 'tag', 'created_at', 'updated_at'])
  - constraint: unique(context_id, tag)
  - constraint: tag != ''
  - constraint: length(tag) <= 64
  - constraint: fk(context_id) references contexts(id) on delete cascade
- `context_references.json` — Many-to-many directed links between contexts (maps to references[] in save_project_context). Used to represent related contexts beyond simple parent/continuation relationships. (18 rows; fields: ['id', 'from_context_id', 'to_context_id', 'relationship', 'created_at', 'updated_at'])
  - constraint: unique(from_context_id, to_context_id, relationship)
  - constraint: from_context_id != to_context_id
  - constraint: relationship in ('related')
  - constraint: fk(from_context_id) references contexts(id) on delete cascade

## Business rules enforced by the tools

- save_project_context must upsert a contexts row with id=params.id, type='project', project_id=params.projectId, content=params.content, metadata=params.metadata (or null), parent_context_id=params.parentContextId (or null), and status='active'.
- save_conversation_context must upsert a contexts row with id=params.id, type='conversation', session_id=params.sessionId, content=params.content, metadata=params.metadata (or null), continuation_of_context_id=params.continuationOf (or null), and status='active'.
- If a project_id does not exist at save time, the service must either (a) reject with a foreign key error or (b) create a placeholder projects row in status='active'; the backend enforces FK integrity and should not allow orphaned project contexts.
- If a session_id does not exist at save time, the service must either (a) reject with a foreign key error or (b) create a placeholder conversation_sessions row in status='active'; the backend enforces FK integrity and should not allow orphaned conversation contexts.
- For contexts.type='project', continuation_of_context_id must be null; for contexts.type='conversation', parent_context_id must be null.
- When parent_context_id is provided, the referenced parent context must exist, be type='project', and have the same project_id as the child context.
- When continuation_of_context_id is provided, the referenced context must exist, be type='conversation', and have the same session_id as the new context.
- save_project_context(tags) and save_conversation_context(tags) must replace the set of tags for that context (delete missing tags; insert new ones) to match the provided list exactly; duplicates in input are ignored via unique(context_id, tag).
- save_project_context(references) must replace the set of context_references edges (relationship='related') for that from_context_id to match the provided list exactly; duplicates are ignored via unique(from_context_id,to_context_id,relationship).
- get_context(id, projectId?) returns the contexts row with that id if status='active'. If projectId is provided, the returned context must be type='project' and project_id=projectId; otherwise return not found.
- list_contexts(projectId?, tag?, type?) returns contexts where status='active' and optional filters apply: type equals provided type; project_id equals provided projectId; and if tag is provided, context must have a matching context_tags.tag.
- Deleting/archiving projects or closing sessions must not automatically delete contexts; contexts remain queryable unless their own status transitions to 'deleted' (FKs are restrict on project/session deletes).
- All writes must update updated_at; creates set created_at=updated_at=now().