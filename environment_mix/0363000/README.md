# Vibe Check — local MCP environment

Vibe Check stores lightweight "sessions" where a user/agent runs the three tools (vibe_check, vibe_distill, vibe_learn) against an in-progress plan or implementation. The backend persists each run’s inputs/outputs, tracks distilled plans, and maintains a small pattern library of recurring issues and recommended fixes learned from prior runs.

Repository: https://github.com/PV-Bhat/vibe-check-mcp-server
Homepage: https://smithery.ai/server/@PV-Bhat/vibe-check-mcp-server

## Datastore

- `workspaces.json` — Tenant container for users/agents using Vibe Check. Used to scope sessions, runs, and learned patterns. (12 rows; fields: ['id', 'name', 'slug', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(slug)
  - constraint: name <> ''
- `sessions.json` — A conversational/analysis session that groups multiple tool runs about the same plan/feature/task. (18 rows; fields: ['id', 'workspace_id', 'title', 'status', 'context', 'opened_at', 'closed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'archived', 'deleted']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete restrict
  - constraint: title <> ''
- `tool_runs.json` — An invocation of one of the three tools. Persists request/response payloads for reproducibility and learning. (19 rows; fields: ['id', 'workspace_id', 'session_id', 'tool_name', 'status', 'request_payload', 'input_text', 'response_payload', 'output_text', 'error_code', 'error_message', 'duration_ms', 'tokens_in', 'tokens_out', 'created_at', 'updated_at', 'started_at', 'finished_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key (session_id) references sessions(id) on delete cascade
  - constraint: duration_ms is null or duration_ms >= 0
  - constraint: tokens_in is null or tokens_in >= 0
- `distilled_plans.json` — Outputs of vibe_distill captured as canonical simplified plans with essential elements and anti-overengineering notes. (19 rows; fields: ['id', 'workspace_id', 'session_id', 'source_run_id', 'status', 'original_summary', 'essential_elements', 'complexity_sources', 'recommended_simplifications', 'notes', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'active', 'superseded', 'deleted']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key (session_id) references sessions(id) on delete cascade
  - constraint: foreign key (source_run_id) references tool_runs(id) on delete restrict
  - constraint: essential_elements is a JSON array (can be empty [])
- `learned_patterns.json` — Pattern library of recurring errors/anti-patterns and their recommended solutions, accumulated by vibe_learn and referenced by vibe_check. (19 rows; fields: ['id', 'workspace_id', 'status', 'pattern_key', 'title', 'problem', 'solution', 'tags', 'evidence_count', 'first_seen_at', 'last_seen_at', 'created_by_run_id', 'updated_by_run_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated', 'deleted']
  - constraint: foreign key (workspace_id) references workspaces(id) on delete restrict
  - constraint: foreign key (created_by_run_id) references tool_runs(id) on delete set null
  - constraint: foreign key (updated_by_run_id) references tool_runs(id) on delete set null
  - constraint: unique(workspace_id, pattern_key)

## Business rules enforced by the tools

- Each tool call (vibe_check, vibe_distill, vibe_learn) must create exactly one tool_runs row with tool_name matching the invoked tool and request_payload equal to the received parameters (empty object allowed).
- tool_runs.status must follow the declared transitions; setting finished_at requires status in {succeeded, failed, cancelled}; setting started_at requires status != queued.
- A distilled_plans row may only be created from a tool_runs row where tool_name = 'vibe_distill' and status = 'succeeded'.
- Only one distilled_plans row may exist per source_run_id (unique(source_run_id)); activating a new distilled plan for a session must supersede any previously active plan in that same session (at most one active per session enforced in application logic).
- A learned_patterns row may be created/updated only from a tool_runs row where tool_name = 'vibe_learn' and status = 'succeeded'; updates increment evidence_count and must update last_seen_at >= first_seen_at.
- vibe_check should read learned_patterns (status='active') in the same workspace to surface relevant warnings; it must not modify learned_patterns directly (only via vibe_learn).
- All entities are workspace-scoped: tool_runs.workspace_id must equal sessions.workspace_id; distilled_plans.workspace_id must equal sessions.workspace_id and tool_runs.workspace_id; learned_patterns.workspace_id must match any referencing tool_runs.workspace_id.
- Deleting a session (status -> deleted) must cascade-delete its distilled_plans and tool_runs, but must not delete learned_patterns; learned_patterns references to deleted tool_runs are set to null via FK rules.