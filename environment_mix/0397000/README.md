# Cursor10x Memory System — local MCP environment

Cursor10x Memory System stores conversational short-term messages, active working-set files, long-term project knowledge (milestones/decisions/requirements), and episodic logs of actions. The main workflows are initializing/ending a conversation by writing messages and creating summary artifacts, and retrieving recent context and stats across all memory subsystems.

Repository: https://github.com/aurda012/cursor10x-mcp
Homepage: https://smithery.ai/server/@aurda012/cursor10x-mcp

## Datastore

- `conversations.json` — A chat/session boundary used to group short-term messages, active files, and episodic logs for a single working thread. (18 rows; fields: ['id', 'external_conversation_key', 'title', 'banner_text', 'status', 'started_at', 'ended_at', 'last_activity_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'ended']
  - constraint: unique(external_conversation_key) where external_conversation_key is not null
  - constraint: started_at <= last_activity_at
  - constraint: ended_at is null when status='active'
  - constraint: ended_at is not null when status='ended'
- `messages.json` — Short-term memory messages for a conversation (user and assistant). Used to retrieve recent messages and form context. (19 rows; fields: ['id', 'conversation_id', 'role', 'content', 'content_format', 'sequence', 'token_count', 'status', 'redacted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['stored', 'redacted']
  - constraint: foreign key(conversation_id) references conversations(id) on delete cascade
  - constraint: unique(conversation_id, sequence)
  - constraint: sequence >= 1
  - constraint: token_count is null or token_count >= 0
- `active_files.json` — Short-term working set of files the user is actively viewing/editing in the context of a conversation. (18 rows; fields: ['id', 'conversation_id', 'path', 'repo_root', 'language', 'status', 'first_seen_at', 'last_accessed_at', 'access_count', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: foreign key(conversation_id) references conversations(id) on delete cascade
  - constraint: unique(conversation_id, repo_root, path)
  - constraint: path != ''
  - constraint: access_count >= 0
- `knowledge_items.json` — Long-term memory store for structured project knowledge: milestones, decisions, and requirements. Items can be created independently or as part of endConversation. (18 rows; fields: ['id', 'conversation_id', 'type', 'title', 'body', 'tags', 'status', 'effective_at', 'supersedes_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded', 'archived']
  - constraint: foreign key(conversation_id) references conversations(id) on delete set null
  - constraint: foreign key(supersedes_id) references knowledge_items(id) on delete set null
  - constraint: title != ''
  - constraint: body != ''
- `episodes.json` — Episodic memory: time-ordered log of actions/events that occurred during a conversation (e.g., ending conversation, key actions taken). (18 rows; fields: ['id', 'conversation_id', 'kind', 'summary', 'payload', 'sequence', 'status', 'occurred_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['recorded', 'voided']
  - constraint: foreign key(conversation_id) references conversations(id) on delete cascade
  - constraint: unique(conversation_id, sequence)
  - constraint: sequence >= 1
  - constraint: summary != ''

## Business rules enforced by the tools

- checkHealth returns healthy only if the database connection is available and all required collections are readable/writable.
- initConversation must create a conversations row with status='active', started_at=now, last_activity_at=now; it may also set banner_text (equivalent of generateBanner) and must return context assembled from messages/active_files/knowledge_items/episodes for that conversation scope.
- storeUserMessage must insert a messages row with role='user', status='stored', and the next sequence value for the conversation; it must update conversations.last_activity_at.
- storeAssistantMessage must insert a messages row with role='assistant', status='stored', and the next sequence value for the conversation; it must update conversations.last_activity_at.
- getRecentMessages must return messages for the relevant conversation ordered by sequence desc/created_at desc and exclude status='redacted' unless explicitly requested by internal policy.
- trackActiveFile must upsert into active_files by (conversation_id, repo_root, path): if exists, set status='active', increment access_count, and set last_accessed_at=now; else create with first_seen_at=now, last_accessed_at=now, access_count=1; it must update conversations.last_activity_at.
- getActiveFiles must return active_files where status='active' for the conversation ordered by last_accessed_at desc.
- storeMilestone/storeDecision/storeRequirement must insert a knowledge_items row with type matching the tool, status='active', and non-empty title/body.
- endConversation must (1) store the assistant message, (2) optionally create a milestone knowledge_items row capturing the milestone, and (3) insert an episodes row (kind='conversation_end') whose payload references any ids created; finally set conversations.status='ended', ended_at=now, last_activity_at=now.
- recordEpisode must insert an episodes row with status='recorded' and the next per-conversation sequence; it must update conversations.last_activity_at.
- getRecentEpisodes must return episodes for the conversation ordered by sequence desc/occurred_at desc and exclude status='voided' unless explicitly requested by internal policy.
- getComprehensiveContext must assemble a response that includes: recent messages, active files, recent episodes, and active knowledge_items; items should be constrained to the current conversation where conversation_id is set plus any global items where conversation_id is null if the system supports global memory.
- getMemoryStats must compute counts over the collections (e.g., total messages, active files, knowledge items by type/status, episodes) and may use token_count where present; negative counts or null aggregates are invalid.
- All per-conversation sequence fields (messages.sequence, episodes.sequence) must be assigned atomically to avoid duplicates under concurrency (e.g., via transaction with SELECT ... FOR UPDATE or database sequence per conversation).
- No writes are allowed to a conversation with status='ended' except appending episodes of kind='postmortem' if explicitly enabled; default behavior rejects storeUserMessage/storeAssistantMessage/trackActiveFile/recordEpisode for ended conversations.