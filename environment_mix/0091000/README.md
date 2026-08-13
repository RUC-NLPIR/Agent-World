# Game Engine Server — local MCP environment

This backend stores iterative game design sessions composed of structured design thoughts (steps), including branching/revisions, implementation notes, UI component plans, and shader/code snippets. The main workflow is: append thoughts to an active design session, derive a live summary view for the current session, and export the full session as HTML documentation.

Repository: https://github.com/smithery-ai
Homepage: https://smithery.ai/server/@mahecode/game-engine-mcp

## Datastore

- `game_design_sessions.json` — Top-level container for a single game design effort (a 'current game design'), including title/description and export metadata. (12 rows; fields: ['id', 'status', 'current_branch_id', 'game_title', 'game_description', 'total_thoughts_estimate', 'last_thought_number', 'last_summary_cache', 'last_export_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'active', 'archived']
  - constraint: total_thoughts_estimate >= 1
  - constraint: last_thought_number >= 0
  - constraint: current_branch_id IS NULL OR length(current_branch_id) <= 128
- `design_thoughts.json` — Atomic design/implementation steps captured via the gamedesignthinking tool, including revisions, branching, mechanics/UI/shader notes, and code snippets. (11 rows; fields: ['id', 'session_id', 'status', 'thought', 'next_thought_needed', 'thought_number', 'total_thoughts', 'is_revision', 'revises_thought_number', 'branch_from_thought_number', 'branch_id', 'game_component', 'library_used', 'code_snippet', 'performance_consideration', 'browser_compatibility', 'difficulty', 'dependencies', 'alternatives', 'mechanics', 'player_experience', 'modern_ui', 'game_title', 'game_description', 'created_at', 'updated_at'])
  - lifecycle `status`: ['recorded', 'superseded', 'deleted']
  - constraint: thought_number >= 1
  - constraint: total_thoughts >= 1
  - constraint: length(thought) > 0
  - constraint: branch_id IS NULL OR length(branch_id) <= 128
- `ui_components.json` — Normalized UI components attached to a specific thought, as provided by gamedesignthinking.uiComponents. (12 rows; fields: ['id', 'thought_id', 'component_type', 'description', 'placement', 'interactivity', 'created_at', 'updated_at'])
  - constraint: length(component_type) > 0
  - constraint: UNIQUE(thought_id, component_type, placement)
- `shader_effects.json` — Custom shader effects attached to a specific thought, as provided by gamedesignthinking.shaders. (12 rows; fields: ['id', 'thought_id', 'shader_type', 'purpose', 'code', 'created_at', 'updated_at'])
  - constraint: length(shader_type) > 0
  - constraint: UNIQUE(thought_id, shader_type, purpose)
- `exports.json` — Export jobs and resulting HTML documentation produced by exportGameDesign. (12 rows; fields: ['id', 'session_id', 'status', 'format', 'html_document', 'error_message', 'created_at', 'updated_at', 'completed_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed']
  - constraint: format = 'html'
  - constraint: html_document IS NOT NULL WHEN status = 'succeeded'
  - constraint: error_message IS NOT NULL WHEN status = 'failed'

## Business rules enforced by the tools

- gamedesignthinking must insert exactly one design_thoughts row per call, with required fields: thought, next_thought_needed, thought_number, total_thoughts.
- design_thoughts.thought_number and design_thoughts.total_thoughts must be >= 1; total_thoughts_estimate on game_design_sessions must be kept >= 1.
- Within a session and branch (branch_id null treated as 'main'), only one non-deleted thought may be active for a given thought_number; additional submissions for the same thought_number must either mark the prior as superseded or be rejected.
- If design_thoughts.is_revision = true, then revises_thought_number must be non-null and refer to an existing thought_number in the same session and branch; the revised thought should be transitioned from recorded -> superseded.
- If design_thoughts.branch_id is non-null, then branch_from_thought_number must be non-null and refer to an existing thought_number in the same session (main branch unless explicitly branching from another branch).
- If game_title or game_description is provided on a thought, the system must set game_design_sessions.game_title/game_description if they are currently null; subsequent attempts to change them must create a new thought (recording the change) but must not overwrite the original session fields unless an explicit 'retitle' administrative operation exists (not in tool surface).
- uiComponents provided to gamedesignthinking must be stored as ui_components rows linked to the created thought; shaders provided must be stored as shader_effects rows linked to the created thought.
- getGameSummary must read from the latest non-deleted thoughts in the session's current_branch_id (or main if null) and return an aggregate that includes at minimum distinct game_component values and distinct library_used values; it may use game_design_sessions.last_summary_cache if updated_at >= latest related thought updated_at.
- exportGameDesign must create an exports row (queued), render HTML by ordering thoughts by thought_number within the current branch, and transition exports.status through queued -> running -> succeeded/failed with completed_at set on terminal states.
- FK integrity: deleting a session is not allowed while it has thoughts or exports; instead sessions are archived. Deleting a thought is a soft delete via status='deleted' and must not physically remove linked ui_components or shader_effects rows.