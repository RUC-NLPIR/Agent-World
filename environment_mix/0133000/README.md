# Clear Thought Server — local MCP environment

Clear Thought Server persists structured reasoning workflows (thinking sequences, decision analyses, scientific inquiries, collaborative sessions, argument maps, and visual diagrams) as versioned sessions with iterative steps. The main workflow is: a client repeatedly calls a tool with a stable session identifier and iteration/thought numbers, and the backend appends/updates step records, enforcing ordering, branching/revisions, and lifecycle completion flags.

Repository: https://github.com/ThinkFar/clear-thought-mcp
Homepage: https://smithery.ai/server/@ThinkFar/clear-thought-mcp

## Datastore

- `reasoning_sessions.json` — Top-level container for any tool run that evolves over time (sequential thinking, mental model application, design pattern application, programming paradigm analysis, debugging approach, decision framework, metacognitive monitoring, scientific method inquiry, structured argumentation, visual reasoning, collaborative reasoning). Identified by the tool-provided session id fields (e.g., decisionId, inquiryId, monitoringId, sessionId) or a server-generated id when absent. (18 rows; fields: ['id', 'tool_name', 'external_session_key', 'title', 'subject_text', 'current_iteration', 'status', 'completed_flag', 'metadata', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'completed', 'archived', 'cancelled']
  - constraint: tool_name is required
  - constraint: current_iteration >= 0
  - constraint: unique(tool_name, external_session_key) where external_session_key is not null
  - constraint: completed_flag implies status in ('completed','archived') OR status remains 'active' but cannot accept further writes when completed_flag=true (enforced in business rules)
- `reasoning_steps.json` — Append-only (or revision-aware) step events within a session. Covers sequential thoughts, stage updates for scientific/decision/metacognitive/collaborative flows, and per-call payload capture for tools with iterative progression. (21 rows; fields: ['id', 'session_id', 'iteration', 'sequence_number', 'step_kind', 'stage', 'content_text', 'payload', 'is_revision', 'revises_sequence_number', 'branch_id', 'branch_from_sequence_number', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['recorded', 'superseded', 'deleted']
  - constraint: foreign key(session_id) references reasoning_sessions(id) on delete cascade
  - constraint: iteration >= 0
  - constraint: sequence_number >= 1
  - constraint: unique(session_id, sequence_number) where status != 'deleted' (prevents duplicate thoughtNumber within a session)
- `decision_items.json` — Normalized sub-entities for the decisionframework tool: options, criteria, and possible outcomes. This allows consistent linking/validation (e.g., outcome.optionId must exist) beyond storing everything in a single JSON payload. (18 rows; fields: ['id', 'session_id', 'item_type', 'external_id', 'name', 'description', 'weight', 'probability', 'value', 'confidence_in_estimate', 'related_option_external_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: foreign key(session_id) references reasoning_sessions(id) on delete cascade
  - constraint: unique(session_id, item_type, external_id) where external_id is not null
  - constraint: weight between 0 and 1 when item_type='criterion'
  - constraint: probability between 0 and 1 when item_type='outcome'
- `collaboration_entities.json` — Normalized sub-entities for collaborativereasoning: personas, contributions, and disagreements (including positions). Stores structured perspective data and enforces that contribution.personaId references a known persona in the session. (17 rows; fields: ['id', 'session_id', 'entity_type', 'external_id', 'persona_name', 'persona_background', 'persona_expertise', 'persona_perspective', 'persona_biases', 'persona_communication', 'contribution_persona_external_id', 'contribution_content', 'contribution_type', 'contribution_confidence', 'contribution_reference_ids', 'disagreement_topic', 'disagreement_positions', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: foreign key(session_id) references reasoning_sessions(id) on delete cascade
  - constraint: unique(session_id, entity_type, external_id) where entity_type='persona' and external_id is not null
  - constraint: contribution_confidence between 0 and 1 when entity_type='contribution'
  - constraint: contribution_type required when entity_type='contribution'
- `visual_diagram_elements.json` — Normalized storage for visualreasoning diagrams and their elements. Each visualreasoning call can create/update/delete elements; this table represents current diagram state while the corresponding reasoning_steps row stores the event history. (19 rows; fields: ['id', 'session_id', 'external_element_id', 'element_type', 'label', 'properties', 'source_external_element_id', 'target_external_element_id', 'contains_external_element_ids', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key(session_id) references reasoning_sessions(id) on delete cascade
  - constraint: unique(session_id, external_element_id)
  - constraint: element_type='edge' implies source_external_element_id is not null and target_external_element_id is not null
  - constraint: properties is required (matches tool schema)

## Business rules enforced by the tools

- For any tool call that includes a stable id (decisionId, inquiryId, monitoringId, collaborativereasoning.sessionId, visualreasoning.diagramId, structuredargumentation.argumentId when provided), the service must upsert reasoning_sessions by (tool_name, external_session_key).
- For sequentialthinking, a call must create a reasoning_steps row with step_kind='sequential_thought', sequence_number=thoughtNumber, payload.totalThoughts=totalThoughts, payload.nextThoughtNeeded=nextThoughtNeeded, and content_text=thought.
- For sequentialthinking, thoughtNumber and totalThoughts must be integers >= 1 at write time; thoughtNumber must be <= totalThoughts unless needsMoreThoughts=true (if provided).
- For sequentialthinking revisions: if isRevision=true then revisesThought must be provided and maps to revises_sequence_number; the prior step with that sequence_number must exist in the same session and is marked status='superseded' when the revision is accepted.
- For sequentialthinking branching: if branchId is provided, it is stored on reasoning_steps.branch_id; if branchFromThought is provided, the referenced sequence_number must exist in the session.
- For decisionframework, reasoning_sessions.metadata must store analysisType, stage, stakeholders, constraints, timeHorizon, riskTolerance, recommendation, rationale, and decisionStatement (mirrored also into subject_text/title as appropriate).
- For decisionframework, each options[] item must upsert a decision_items row with item_type='option' and external_id=options[i].id (or a generated stable surrogate if missing); criteria[] upserts item_type='criterion'; possibleOutcomes[] upserts item_type='outcome'.
- For decisionframework, each possibleOutcomes[].optionId must match an existing option external_id within the same session at the time the outcome is recorded; otherwise reject the request.
- For collaborativereasoning, personas[] must be upserted as collaboration_entities(entity_type='persona'); contributions[] must be inserted/upserted as entity_type='contribution' and must reference an existing persona via contribution_persona_external_id == persona.external_id within the same session.
- For collaborativereasoning, disagreements[] positions[].personaId must reference an existing persona in the same session; otherwise reject the request.
- For metacognitivemonitoring, reasoning_steps.payload must store knowledgeAssessment, claims, reasoningSteps, suggestedAssessments, overallConfidence, uncertaintyAreas, recommendedApproach, stage, and nextAssessmentNeeded; all confidenceScore/logicalValidity/inferenceStrength fields must be validated to be within [0,1].
- For scientificmethod, hypothesis.status must be one of (proposed, testing, supported, refuted, refined) and can only transition forward: proposed -> testing -> (supported|refuted|refined); refined -> testing is allowed when hypothesis.refinementOf is set.
- For visualreasoning, each call creates a reasoning_steps row (step_kind='visual_update') capturing operation/transformationType/observation/insight/hypothesis/nextOperationNeeded; additionally, elements[] are applied to visual_diagram_elements as the current state: create/update upserts to status='active', delete sets status='deleted'.
- For visualreasoning, edge elements must reference existing (non-deleted) source/target elements in the same session after applying the batch; otherwise reject the request.
- A session is marked completed (reasoning_sessions.completed_flag=true and status may transition to 'completed') when the latest call indicates no further steps are needed: sequentialthinking.nextThoughtNeeded=false, collaborativereasoning.nextContributionNeeded=false, decisionframework.nextStageNeeded=false, metacognitivemonitoring.nextAssessmentNeeded=false, scientificmethod.nextStageNeeded=false, structuredargumentation.nextArgumentNeeded=false, visualreasoning.nextOperationNeeded=false.
- After a session is completed_flag=true, additional writes to that session must be rejected unless the incoming request explicitly indicates a continuation (e.g., sequentialthinking.needsMoreThoughts=true or a new iteration greater than current_iteration) and the backend reopens the session by transitioning status from completed -> active (if allowed by policy).