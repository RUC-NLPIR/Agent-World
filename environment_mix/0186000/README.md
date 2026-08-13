# Clear Thought Server — local MCP environment

Clear Thought Server persists structured reasoning workflows as long-lived sessions (sequential thinking, collaboration, decision analysis, metacognitive monitoring, scientific inquiry, structured argumentation, and visual diagrams). Each tool call appends or updates state within a session identified by a vendor-provided external ID (e.g., sessionId/decisionId/etc.), enabling iterative, branchable reasoning with lifecycle status, ordering, and integrity constraints across nested artifacts.

Repository: https://github.com/chirag127/Clear-Thought-MCP-server
Homepage: https://smithery.ai/server/@chirag127/clear-thought-mcp-server

## Datastore

- `reasoning_sessions.json` — Top-level container for iterative reasoning workflows. One row per externally identified workflow instance (e.g., collaboration sessionId, decision decisionId, monitoring monitoringId, scientific inquiry inquiryId, argument thread argumentId group, or diagram diagramId). (19 rows; fields: ['id', 'session_type', 'external_id', 'title', 'iteration', 'stage', 'status', 'next_action_needed', 'context_text', 'stakeholders', 'constraints_text', 'time_horizon', 'risk_tolerance', 'analysis_type', 'overall_confidence', 'uncertainty_areas', 'recommended_approach', 'diagram_type', 'final_text', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'paused', 'completed', 'archived']
  - constraint: unique(session_type, external_id)
  - constraint: iteration >= 0
  - constraint: overall_confidence is null OR (overall_confidence >= 0 AND overall_confidence <= 1)
  - constraint: risk_tolerance is null OR risk_tolerance in ('risk-averse','risk-neutral','risk-seeking')
- `session_events.json` — Append-only event log for sequentialthinking and other stepwise tools. Captures ordering, branching/revision metadata, and generic event payloads for audit and replay. (18 rows; fields: ['id', 'session_id', 'tool_name', 'event_type', 'sequence_number', 'iteration', 'payload', 'created_at', 'updated_at'])
  - lifecycle `event_type`: ['thought', 'revision', 'branch', 'model_application', 'pattern_application', 'paradigm_application', 'debugging_application', 'contribution', 'decision_update', 'monitoring_update', 'scientific_update', 'argument', 'diagram_operation']
  - constraint: foreign key(session_id) references reasoning_sessions(id) on delete cascade
  - constraint: sequence_number >= 1
  - constraint: iteration >= 0
  - constraint: unique(session_id, sequence_number)
- `collaboration_personas.json` — Personas participating in a collaborativereasoning session. Stored separately for validation and to support contributions referencing personaId. (18 rows; fields: ['id', 'session_id', 'external_persona_id', 'name', 'expertise', 'background', 'perspective', 'biases', 'communication_style', 'communication_tone', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'inactive']
  - constraint: foreign key(session_id) references reasoning_sessions(id) on delete cascade
  - constraint: unique(session_id, external_persona_id)
  - constraint: communication_style <> ''
  - constraint: communication_tone <> ''
- `decision_components.json` — Normalized components for decisionframework: options, criteria, and outcomes. Allows stable referencing (optionId) and enforces weights/probabilities bounds. (18 rows; fields: ['id', 'session_id', 'component_type', 'external_component_id', 'name', 'description', 'weight', 'probability', 'value', 'confidence_in_estimate', 'option_external_id', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded', 'deleted']
  - constraint: foreign key(session_id) references reasoning_sessions(id) on delete cascade
  - constraint: component_type in ('option','criterion','outcome')
  - constraint: component_type='option' implies name is not null
  - constraint: component_type='criterion' implies (name is not null AND weight is not null AND weight>=0 AND weight<=1)
- `scientific_artifacts.json` — Artifacts for scientificmethod: hypotheses, variables, and experiments (including predictions). Stores structured fields and enforces hypothesis/experiment status and bounds. (17 rows; fields: ['id', 'session_id', 'artifact_type', 'external_artifact_id', 'parent_external_id', 'statement', 'domain', 'confidence', 'hypothesis_status', 'assumptions', 'alternative_to', 'refinement_of', 'variable_name', 'variable_type', 'operationalization', 'experiment_design', 'methodology', 'control_measures', 'results', 'outcome_matched', 'unexpected_observations', 'limitations', 'next_steps', 'prediction_if', 'prediction_then', 'prediction_else', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded', 'deleted']
  - constraint: foreign key(session_id) references reasoning_sessions(id) on delete cascade
  - constraint: artifact_type='hypothesis' implies (external_artifact_id is not null AND statement is not null AND assumptions is not null AND domain is not null AND confidence is not null AND confidence>=0 AND confidence<=1 AND hypothesis_status is not null)
  - constraint: artifact_type='variable' implies (parent_external_id is not null AND variable_name is not null AND variable_type in ('independent','dependent','controlled','confounding'))
  - constraint: artifact_type='experiment' implies (external_artifact_id is not null AND parent_external_id is not null AND experiment_design is not null AND methodology is not null AND control_measures is not null)

## Business rules enforced by the tools

- For any tool call that includes an external identifier (sessionId/decisionId/monitoringId/inquiryId/diagramId), the service MUST upsert reasoning_sessions by (session_type, external_id) and set iteration, stage (if provided), and next_action_needed to the latest provided value.
- sequentialthinking calls MUST append a session_events row with tool_name='sequentialthinking', event_type in ('thought','revision','branch') and payload containing thought, thoughtNumber, totalThoughts, nextThoughtNeeded, isRevision, revisesThought, branchFromThought, branchId, needsMoreThoughts. thoughtNumber and totalThoughts MUST be >= 1; if isRevision=true then revisesThought MUST be provided and refer to an existing thoughtNumber within the same session.
- For collaborativereasoning, all personas in the request MUST exist in collaboration_personas for that session after the call (insert missing, update existing by external_persona_id). Each contribution MUST reference an existing personaId (external_persona_id) in that same session; confidence MUST be within [0,1].
- For decisionframework, options/criteria/possibleOutcomes MUST be synchronized into decision_components. Each possibleOutcome.optionId MUST match an option external_component_id present in the same session; probability and confidenceInEstimate MUST be within [0,1]. If criteria are present, the sum of active criterion weights SHOULD be within [0.99,1.01] (soft constraint) and each individual weight MUST be within [0,1] (hard constraint).
- For metacognitivemonitoring, overallConfidence and any claim/reasoning step confidence/validity metrics in payload MUST be within [0,1]. uncertaintyAreas MUST be stored on the session and MUST be a non-empty array when nextAssessmentNeeded=true.
- For scientificmethod, when hypothesis is provided it MUST be persisted as scientific_artifacts rows: one 'hypothesis' row for hypothesisId, one 'variable' row per variable referencing parent_external_id=hypothesisId, one 'experiment' row for experimentId referencing parent_external_id=hypothesisId, and one 'prediction' row per prediction referencing parent_external_id=experimentId. hypothesis.status transitions MUST follow: proposed -> testing -> (supported|refuted|refined); refined may transition back to testing.
- For structuredargumentation, each call MUST append a session_events row with event_type='argument' and payload containing claim, premises, conclusion, argumentType, confidence, respondsTo/supports/contradicts, strengths/weaknesses, nextArgumentNeeded, suggestedNextTypes. confidence MUST be within [0,1]. If respondsTo is provided, it MUST refer to an argumentId that exists earlier in the same session's event stream.
- For visualreasoning, each call MUST append a session_events row with event_type='diagram_operation' and payload containing operation, diagramId, diagramType, elements, transformationType, observation/insight/hypothesis, nextOperationNeeded. For elements of type 'edge', source and target MUST be provided and refer to existing node element ids in the current diagram state (validated by replaying events for that diagramId).
- mentalmodel/designpattern/programmingparadigm/debuggingapproach are stateless advisory tools but MUST still be persisted as session_events (event_type model_application/pattern_application/paradigm_application/debugging_application) to support auditability; required fields (modelName/patternName/paradigmName/approachName and problem/context/issue) MUST be present in payload.