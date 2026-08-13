# React Native Skia Animation Thinking Tool — local MCP environment

This backend stores structured, multi-step "thinking sessions" used to analyze and solve React Native Skia animation problems. Each session contains ordered thoughts (optionally branching and revising prior thoughts) and captures technique, performance notes, code snippets, and expected visual effects for each step.

Repository: https://github.com/mahecode/mcp-react-native-skia
Homepage: https://smithery.ai/server/@mahecode/mcp-react-native-skia

## Datastore

- `thinking_sessions.json` — A single end-to-end Skia animation problem-solving session containing a sequence of thoughts and optional branches/revisions. (18 rows; fields: ['id', 'status', 'title', 'context', 'estimated_total_thoughts', 'last_thought_number', 'default_branch_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'completed', 'abandoned']
  - constraint: estimated_total_thoughts >= 1
  - constraint: last_thought_number >= 0
  - constraint: default_branch_id <> ''
  - constraint: updated_at >= created_at
- `session_thoughts.json` — Individual thought steps recorded for a session. Supports branching, revisions, and Skia technique metadata. (18 rows; fields: ['id', 'session_id', 'status', 'thought_number', 'total_thoughts', 'thought', 'next_thought_needed', 'needs_more_thoughts', 'is_revision', 'revises_thought_number', 'branch_from_thought_number', 'branch_id', 'animation_technique', 'performance_consideration', 'code_snippet', 'visual_effect', 'created_at', 'updated_at'])
  - lifecycle `status`: ['recorded', 'superseded', 'deleted']
  - constraint: foreign key (session_id) references thinking_sessions(id) on delete cascade
  - constraint: thought_number >= 1
  - constraint: total_thoughts >= 1
  - constraint: branch_id <> ''
- `thought_links.json` — Explicit graph edges between thoughts to support revision and branching relationships beyond simple numbering (e.g., revise-of, branch-from). (18 rows; fields: ['id', 'session_id', 'from_thought_id', 'to_thought_id', 'link_type', 'created_at', 'updated_at'])
  - lifecycle `link_type`: ['revises', 'branches_from']
  - constraint: foreign key (session_id) references thinking_sessions(id) on delete cascade
  - constraint: foreign key (from_thought_id) references session_thoughts(id) on delete cascade
  - constraint: foreign key (to_thought_id) references session_thoughts(id) on delete restrict
  - constraint: from_thought_id <> to_thought_id
- `tool_invocations.json` — Immutable log of each skiaanimationthinking tool call payload for audit/debugging and replay. (19 rows; fields: ['id', 'tool_name', 'session_id', 'thought_id', 'request_payload', 'response_payload', 'created_at', 'updated_at'])
  - lifecycle `tool_name`: ['skiaanimationthinking']
  - constraint: foreign key (session_id) references thinking_sessions(id) on delete set null
  - constraint: foreign key (thought_id) references session_thoughts(id) on delete set null
  - constraint: updated_at >= created_at

## Business rules enforced by the tools

- On each skiaanimationthinking invocation, the service must persist the full request payload in tool_invocations.request_payload.
- If a session_id is not supplied by the caller (or cannot be inferred), the service must create a new thinking_sessions row with status='active', estimated_total_thoughts=request.totalThoughts, last_thought_number=0, and default_branch_id='main'.
- For each invocation, the service must create exactly one session_thoughts row linked to the session, with thought=request.thought, next_thought_needed=request.nextThoughtNeeded, thought_number=request.thoughtNumber, total_thoughts=request.totalThoughts.
- The service must reject any request where thoughtNumber < 1 or totalThoughts < 1.
- The service must reject insertion when (session_id, branch_id, thought_number) already exists for a non-deleted thought; callers must use isRevision + revisesThoughtNumber (or a new branch) instead of overwriting.
- If branchId is omitted/empty in the request, the service must store branch_id = thinking_sessions.default_branch_id.
- If isRevision=true, the service must require revisesThought to be provided and must create a thought_links row with link_type='revises' connecting the new thought to the revised thought within the same session; additionally, the revised thought should be marked status='superseded' (unless already deleted).
- If branchFromThought is provided, the service must create a thought_links row with link_type='branches_from' from the new thought to the referenced thought within the same session; branch_id must be provided or defaulted.
- Referenced thoughts for revisesThought and branchFromThought must exist within the same session; otherwise the request must be rejected.
- When a thought is stored with nextThoughtNeeded=false (or needsMoreThoughts=false when provided), the service should mark thinking_sessions.status='completed' if the thought belongs to the default branch and no other active branches are in progress; otherwise the session may remain 'active'.
- thinking_sessions.estimated_total_thoughts must be updated to max(existing_estimate, request.totalThoughts) and last_thought_number must be updated to max(existing_last, request.thoughtNumber) after a successful thought insert.
- tool_invocations.thought_id must reference the newly created session_thoughts row when persistence succeeds.