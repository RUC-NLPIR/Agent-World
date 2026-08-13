# Sequential Thinking Tools — local MCP environment

This backend stores sequential problem-solving sessions composed of ordered thoughts, optional branching/revision links, and step recommendations (including recommended tools and suggested inputs). The main workflow is: a client initializes a session with an allowed toolset, then repeatedly submits thought events that append to a session timeline and may update the current/previous/remaining step guidance until the session is completed.

Repository: https://github.com/xinzhongyouhai/mcp-sequentialthinking-tools
Homepage: https://smithery.ai/server/@xinzhongyouhai/mcp-sequentialthinking-tools

## Datastore

- `workspaces.json` — Tenant container for organizing sessions and enforcing per-workspace quotas/rate limits. (12 rows; fields: ['id', 'name', 'status', 'max_active_sessions', 'max_thoughts_per_session', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(name)
  - constraint: max_active_sessions >= 1
  - constraint: max_thoughts_per_session >= 1
- `api_keys.json` — API keys used to authenticate tool calls and bind them to a workspace; includes per-key enable/disable and optional scoping. (12 rows; fields: ['id', 'workspace_id', 'name', 'key_hash', 'status', 'allowed_tools', 'last_used_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'revoked']
  - constraint: unique(workspace_id, name)
  - constraint: key_hash is unique
  - constraint: allowed_tools length >= 1
- `thinking_sessions.json` — A sequential thinking run/session that groups thoughts and step recommendations into a single evolving reasoning trace. (12 rows; fields: ['id', 'workspace_id', 'api_key_id', 'status', 'title', 'tool_context', 'current_thought_number', 'estimated_total_thoughts', 'next_thought_needed', 'needs_more_thoughts', 'remaining_steps', 'created_at', 'updated_at', 'completed_at'])
  - lifecycle `status`: ['active', 'completed', 'cancelled', 'archived']
  - constraint: estimated_total_thoughts >= 1
  - constraint: current_thought_number >= 0
  - constraint: tool_context length >= 1
- `thoughts.json` — Individual thought events in a session; supports ordered thinking, revisions, and branching references. (18 rows; fields: ['id', 'session_id', 'status', 'thought_number', 'total_thoughts', 'thought', 'next_thought_needed', 'needs_more_thoughts', 'is_revision', 'revises_thought_number', 'branch_from_thought_number', 'branch_id', 'current_step', 'previous_steps', 'remaining_steps', 'created_at', 'updated_at'])
  - lifecycle `status`: ['committed', 'superseded', 'deleted']
  - constraint: thought_number >= 1
  - constraint: total_thoughts >= 1
  - constraint: unique(session_id, thought_number, branch_id) where status != 'deleted'
  - constraint: is_revision = true implies revises_thought_number is not null
- `session_steps.json` — Normalized step recommendations produced over time within a session, enabling querying and integrity checks across thought events. (18 rows; fields: ['id', 'session_id', 'thought_id', 'status', 'kind', 'step_description', 'expected_outcome', 'next_step_conditions', 'recommended_tools', 'created_at', 'updated_at'])
  - lifecycle `status`: ['proposed', 'superseded', 'completed']
  - constraint: recommended_tools length >= 1
  - constraint: For each recommended_tools[*]: 0 <= confidence <= 1
  - constraint: For each recommended_tools[*]: priority is a finite number
  - constraint: For each recommended_tools[*].tool_name: must be in thinking_sessions.tool_context at time of creation

## Business rules enforced by the tools

- Each sequentialthinking_tools call must authenticate to an active api_keys row whose workspace is active; otherwise reject.
- A session is created implicitly on the first thought for a new session_id (or explicitly by the API layer); tool_context must be provided at session creation and must be a non-empty subset of api_keys.allowed_tools.
- For a given thinking_sessions.id, thoughts.thought_number must be >= 1 and generally non-decreasing within a branch_id; inserting a thought_number lower than the session's current_thought_number is only allowed when is_revision=true or branch_id changes.
- If thoughts.is_revision=true then thoughts.revises_thought_number must be set and must refer to an existing (non-deleted) thought_number within the same session (and typically same branch_id unless explicitly allowed by product policy).
- If thoughts.branch_from_thought_number is set, it must refer to an existing (non-deleted) thought_number within the same session; branch_id must be set when branching is used.
- On each accepted tool call, thinking_sessions.current_thought_number, estimated_total_thoughts, next_thought_needed, needs_more_thoughts, and remaining_steps are updated from the latest payload.
- If next_thought_needed=false (and/or needs_more_thoughts=false), the API may transition thinking_sessions.status from active to completed and set completed_at.
- Enforce workspace quota: number of active sessions for a workspace cannot exceed workspaces.max_active_sessions.
- Enforce session quota: count of non-deleted thoughts per session cannot exceed workspaces.max_thoughts_per_session.
- If a new thought supersedes an earlier thought (revision policy), mark the earlier thought status as superseded; deleted is a terminal state.
- When thoughts.current_step or thoughts.previous_steps are provided, the service must persist them either embedded on thoughts and/or normalized into session_steps; normalized session_steps rows must mirror required fields (step_description, recommended_tools, expected_outcome) and validate confidence range [0,1].
- Tool recommendations must not include tool_name values outside the session tool_context; otherwise reject or downrank before persistence depending on policy (default: reject).