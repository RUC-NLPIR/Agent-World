# Lotus Wisdom — local MCP environment

Lotus Wisdom stores guided contemplative/problem-solving journeys composed of sequential processing steps tagged with Lotus Sutra-inspired techniques. The core workflow is: a client appends steps via the lotuswisdom tool, the service tracks tag-path and domain movement over time, and once completion conditions are met it marks the journey WISDOM_READY; lotuswisdom_summary reads back the current journey state and a synthesized summary payload.

Repository: https://github.com/linxule/lotus-wisdom-mcp
Homepage: https://smithery.ai/server/@linxule/lotus-wisdom-mcp

## Datastore

- `journeys.json` — A single contemplative/problem-solving journey/session. Tracks overall progress, readiness state, and current computed positions (tag-path and wisdom-domain movement). (18 rows; fields: ['id', 'status', 'current_step_number', 'total_steps_estimate', 'next_step_needed', 'last_tag', 'tag_path', 'domain_state', 'summary_text', 'summary_updated_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['IN_PROGRESS', 'WISDOM_READY', 'CANCELLED']
  - constraint: current_step_number >= 0
  - constraint: total_steps_estimate >= 1
  - constraint: updated_at >= created_at
- `steps.json` — Individual processing steps appended via the lotuswisdom tool. Each step stores the exact tool parameters plus server-side normalization and ordering. (19 rows; fields: ['id', 'journey_id', 'status', 'tag', 'content', 'step_number', 'total_steps', 'next_step_needed', 'is_meditation', 'meditation_duration_seconds', 'server_notes', 'created_at', 'updated_at'])
  - lifecycle `status`: ['RECEIVED', 'APPLIED', 'REJECTED']
  - constraint: foreign key (journey_id) references journeys(id) on delete cascade
  - constraint: unique(journey_id, step_number)
  - constraint: step_number >= 1
  - constraint: total_steps >= 1
- `domain_movements.json` — Normalized events representing the service's tracked wisdom-domain movements derived from steps. Supports reporting/summary and auditing of how the journey progressed across conceptual domains. (18 rows; fields: ['id', 'journey_id', 'step_id', 'sequence_index', 'domain_from', 'domain_to', 'movement_reason', 'created_at', 'updated_at'])
  - lifecycle `sequence_index`: []
  - constraint: foreign key (journey_id) references journeys(id) on delete cascade
  - constraint: foreign key (step_id) references steps(id) on delete cascade
  - constraint: unique(journey_id, sequence_index)
  - constraint: sequence_index >= 1
- `tag_path_nodes.json` — Normalized representation of the journey's tag path, allowing exact reconstruction and enforcement of ordering/uniqueness beyond the array cached on journeys.tag_path. (19 rows; fields: ['id', 'journey_id', 'step_id', 'path_index', 'tag', 'created_at', 'updated_at'])
  - lifecycle `path_index`: []
  - constraint: foreign key (journey_id) references journeys(id) on delete cascade
  - constraint: foreign key (step_id) references steps(id) on delete cascade
  - constraint: unique(journey_id, path_index)
  - constraint: path_index >= 1

## Business rules enforced by the tools

- Each call to tool lotuswisdom creates a new steps row with status=RECEIVED, then either transitions it to APPLIED (and updates journeys) or to REJECTED (and does not change journeys).
- A journey is created automatically on the first accepted step if no active journey exists for the caller context; otherwise the latest IN_PROGRESS journey is used (implementation-specific session binding).
- steps.tag, steps.content, steps.step_number, steps.total_steps, and steps.next_step_needed are required and must conform to the tool schema; step_number >= 1 and total_steps >= 1.
- If steps.is_meditation is true, steps.meditation_duration_seconds must be between 1 and 10 inclusive; if is_meditation is false or null, meditation_duration_seconds must be null.
- For a given journey, step_number must be unique and strictly non-decreasing compared to journeys.current_step_number; out-of-order or duplicate step_number submissions must be REJECTED.
- On applying a step, journeys.current_step_number, journeys.total_steps_estimate, journeys.next_step_needed, journeys.last_tag, journeys.updated_at, and journeys.tag_path (cached) must be updated to reflect the newly applied step.
- On applying a step, the backend may insert 0..N domain_movements rows and exactly 0..1 tag_path_nodes row (depending on whether the tag advances the path); path_index and sequence_index must be contiguous per journey (no gaps).
- A journey transitions to WISDOM_READY iff the latest applied step indicates completion, enforced as: steps.next_step_needed=false OR steps.tag='complete'; once WISDOM_READY, additional lotuswisdom calls must be REJECTED or must create a new journey (implementation policy).
- tool lotuswisdom_summary returns the latest journey's summary_text, status, current_step_number, total_steps_estimate, next_step_needed, and reconstructed tag_path/domain movement derived from tag_path_nodes/domain_movements; if summary_text is stale or null, it must be recomputed and journeys.summary_updated_at updated.
- Deleting/cancelling a journey (if supported internally) must cascade-delete steps, domain_movements, and tag_path_nodes via FK on delete cascade.