# Clear Thought — local MCP environment

Clear Thought stores structured reasoning work within user sessions: sequential thoughts, framework runs (mental models, debugging, socratic, etc.), collaborative persona-based discussions, and scientific inquiries (hypotheses/experiments). The core workflows are: append/branch/revise thoughts over time, record framework iterations as session artifacts, and export/import full session state for backup or sharing.

Repository: https://github.com/waldzellai/waldzell-mcp
Homepage: https://smithery.ai/server/@waldzellai/clear-thought

## Datastore

- `sessions.json` — Top-level container for a user's reasoning work. Drives session_info, session_export, and session_import. Holds basic stats and lifecycle. (18 rows; fields: ['id', 'status', 'title', 'client_session_key', 'last_activity_at', 'total_artifacts', 'total_thoughts', 'total_branches', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'archived', 'deleted']
  - constraint: total_artifacts >= 0
  - constraint: total_thoughts >= 0
  - constraint: total_branches >= 0
  - constraint: unique(client_session_key) where client_session_key is not null
- `thoughts.json` — Sequentialthinking log entries with branching and revision support. Each row corresponds to one tool call step and can revise a prior thought. (18 rows; fields: ['id', 'session_id', 'status', 'thought', 'thought_number', 'total_thoughts', 'next_thought_needed', 'needs_more_thoughts', 'branch_id', 'branch_from_thought_number', 'is_revision', 'revises_thought_number', 'supersedes_thought_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded', 'deleted']
  - constraint: foreign key(session_id) references sessions(id) on delete cascade
  - constraint: thought_number >= 1
  - constraint: total_thoughts >= thought_number
  - constraint: branch_from_thought_number is null or branch_from_thought_number >= 1
- `artifacts.json` — Generic storage for non-sequentialthinking framework runs (mentalmodel, debuggingapproach, socraticmethod, creativethinking, systemsthinking, structuredargumentation, decisionframework, metacognitivemonitoring, visualreasoning). Each tool call writes/updates a single artifact keyed by its external id where provided (e.g., decisionId, monitoringId, diagramId). (19 rows; fields: ['id', 'session_id', 'status', 'tool_name', 'external_object_id', 'iteration', 'stage', 'next_needed', 'payload', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'finalized', 'deleted']
  - constraint: foreign key(session_id) references sessions(id) on delete cascade
  - constraint: iteration is null or iteration >= 0
  - constraint: external_object_id is null or length(external_object_id) between 1 and 128
  - constraint: unique(session_id, tool_name, external_object_id) where external_object_id is not null and status != 'deleted'
- `collaboration_sessions.json` — State and log of collaborativereasoning runs, including personas and contributions per iteration/stage. The tool is modeled explicitly because it contains nested arrays with strict constraints (confidence range, persona references). (18 rows; fields: ['id', 'session_id', 'external_session_id', 'status', 'topic', 'stage', 'active_persona_id', 'iteration', 'next_contribution_needed', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'completed', 'deleted']
  - constraint: foreign key(session_id) references sessions(id) on delete cascade
  - constraint: unique(session_id, external_session_id) where status != 'deleted'
  - constraint: iteration >= 0
  - constraint: length(external_session_id) between 1 and 128
- `collaboration_entities.json` — Child table storing collaborativereasoning.personas and collaborativereasoning.contributions as two row types. This avoids additional collections while preserving strict schema and referential integrity between contributions and personas. (18 rows; fields: ['id', 'collaboration_session_id', 'entity_type', 'persona_id', 'persona_name', 'persona_expertise', 'persona_background', 'persona_perspective', 'persona_biases', 'persona_comm_style', 'persona_comm_tone', 'contribution_type', 'contribution_content', 'contribution_confidence', 'reference_ids', 'iteration', 'created_at', 'updated_at'])
  - lifecycle `entity_type`: ['persona', 'contribution']
  - constraint: foreign key(collaboration_session_id) references collaboration_sessions(id) on delete cascade
  - constraint: entity_type='persona' implies persona_id is not null and persona_name is not null and persona_expertise is not null and persona_background is not null and persona_perspective is not null and persona_biases is not null and persona_comm_style is not null and persona_comm_tone is not null
  - constraint: entity_type='contribution' implies persona_id is not null and contribution_type is not null and contribution_content is not null and contribution_confidence is not null
  - constraint: contribution_confidence is null or (contribution_confidence >= 0 and contribution_confidence <= 1)
- `scientific_inquiries.json` — Stateful storage for scientificmethod runs, including inquiry stage and nested hypothesis/experiment objects. Modeled explicitly because the tool includes multiple ids (inquiryId, hypothesisId, experimentId) and status transitions. (20 rows; fields: ['id', 'session_id', 'external_inquiry_id', 'status', 'stage', 'observation', 'question', 'analysis', 'conclusion', 'iteration', 'next_stage_needed', 'hypothesis', 'experiment', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'completed', 'deleted']
  - constraint: foreign key(session_id) references sessions(id) on delete cascade
  - constraint: unique(session_id, external_inquiry_id) where status != 'deleted'
  - constraint: iteration >= 0
  - constraint: length(external_inquiry_id) between 1 and 128

## Business rules enforced by the tools

- session_info returns aggregates derived from sessions (cached totals) plus recent activity pulled from newest thoughts/artifacts/collaboration_sessions/scientific_inquiries ordered by created_at desc.
- session_export(format='json') must export a consistent snapshot containing the session row plus all related thoughts, artifacts, collaboration_sessions, collaboration_entities, and scientific_inquiries; snapshot must be taken in a single transaction/consistent read.
- session_export(format='summary') must not include full payload blobs; it should include counts and recent titles/first 200 chars of content fields per entity.
- session_import(sessionData) must parse as JSON; if merge=false, create a new sessions row and import all child entities with newly generated internal ids, preserving external_* ids and tool payloads; if merge=true, upsert by (session.client_session_key if present else session.id mapping in import header), and upsert child records by their natural keys (thoughts by (branch_id, thought_number), artifacts by (tool_name, external_object_id), collaboration_sessions by external_session_id, scientific_inquiries by external_inquiry_id).
- sequentialthinking writes a thoughts row; if isRevision=true it must locate the prior thought being revised by (session_id, branch_id, revises_thought_number, status='active') and mark it superseded, setting supersedes_thought_id on the new row; revisions cannot target a thought_number greater than the current thought_number.
- sequentialthinking branching requires branch_id when branch_from_thought_number is provided; branch_from_thought_number must exist as an active thought in the same session on mainline or same branch depending on implementation, and must be <= thought_number.
- For collaborativereasoning, all contribution rows in a given tool call must reference a persona_id that exists among persona rows for the same collaboration_session_id; active_persona_id must also exist among personas.
- For collaborativereasoning, contribution_confidence must be within [0,1] inclusive; invalid values reject the write.
- For mentalmodel/debuggingapproach/socraticmethod/creativethinking/systemsthinking/structuredargumentation/decisionframework/metacognitivemonitoring/visualreasoning tool calls, the backend must store the full request in artifacts.payload and set artifacts.next_needed from the corresponding boolean parameter; for tools with an external id, external_object_id is required and must match the id inside payload.
- For scientificmethod, the row is identified by (session_id, external_inquiry_id). Updates must keep scientific_inquiries.stage in the allowed enum; if hypothesis is provided it must include required nested fields per schema and hypothesis.status transitions are monotonic except that 'refined' may follow any prior status.
- Deleted sessions cascade-delete (or soft-delete) all child entities; session_export must not include entities with status/entity lifecycle marked deleted unless explicitly requested (not present in tool surface).
- All write operations must update sessions.last_activity_at and increment/decrement cached counters in sessions consistently within the same transaction.