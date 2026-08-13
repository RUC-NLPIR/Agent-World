# Collaborative Reasoning Server — local MCP environment

This backend stores collaborative reasoning sessions where multiple expert personas contribute structured inputs (observations, questions, insights, etc.) through staged workflows. It tracks personas, contributions with linkage to prior contributions, explicit disagreements and their resolutions, and evolving session outputs like key insights and final recommendations.

Repository: https://github.com/waldzellai/model-enhancement-servers
Homepage: https://smithery.ai/server/@waldzellai/collaborative-reasoning

## Datastore

- `cr_sessions.json` — Top-level collaborative reasoning session. Stores the current stage, active/next persona pointers, iteration state, and synthesized outputs (insights/consensus/open questions/final recommendation). Mirrors the tool's session-level parameters. (12 rows; fields: ['id', 'topic', 'status', 'stage', 'active_persona_id', 'next_persona_id', 'iteration', 'next_contribution_needed', 'suggested_contribution_types', 'key_insights', 'consensus_points', 'open_questions', 'final_recommendation', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'completed', 'archived']
  - constraint: unique(id)
  - constraint: iteration >= 0
  - constraint: stage in ('problem-definition','ideation','critique','integration','decision','reflection')
  - constraint: suggested_contribution_types elements in ('observation','question','insight','concern','suggestion','challenge','synthesis')
- `cr_personas.json` — Personas participating in a session, including expertise, background, perspective, biases, and communication style/tone. Tool-provided persona.id is stored as the primary key per session/persona. (35 rows; fields: ['id', 'session_id', 'name', 'expertise', 'background', 'perspective', 'biases', 'communication_style', 'communication_tone', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'removed']
  - constraint: unique(session_id, id)
  - constraint: expertise length >= 1
  - constraint: biases length >= 0
  - constraint: communication_style is not null
- `cr_contributions.json` — Atomic contributions made by personas during a session. Supports contribution types, confidence, and references to prior contributions (many-to-many via cr_contribution_references). (32 rows; fields: ['id', 'session_id', 'persona_id', 'content', 'type', 'confidence', 'sequence', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'retracted']
  - constraint: unique(session_id, sequence)
  - constraint: confidence >= 0 and confidence <= 1
  - constraint: type in ('observation','question','insight','concern','suggestion','challenge','synthesis')
- `cr_contribution_references.json` — Join table implementing contributions[].referenceIds: links a contribution to earlier contributions it builds upon. (31 rows; fields: ['id', 'session_id', 'from_contribution_id', 'to_contribution_id', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active']
  - constraint: unique(from_contribution_id, to_contribution_id)
  - constraint: from_contribution_id != to_contribution_id
  - constraint: FK integrity: from_contribution_id and to_contribution_id must belong to same session_id
  - constraint: No forward references: referenced contribution sequence < referencing contribution sequence (enforced in application or deferred constraint)
- `cr_disagreements.json` — Structured disagreements in a session, capturing a topic, positions held by personas (stored as JSON array), and optional resolution details. Maps to disagreements[] including positions[] and resolution. (37 rows; fields: ['id', 'session_id', 'topic', 'positions', 'resolution_type', 'resolution_description', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'resolved', 'tabled']
  - constraint: positions length >= 1
  - constraint: resolution_type is null and resolution_description is null when status = 'open'
  - constraint: resolution_type is not null and resolution_description is not null when status = 'resolved'
  - constraint: if status = 'tabled' then resolution_type may be 'tabled' or null (implementation choice), but resolution_description may be present

## Business rules enforced by the tools

- collaborativeReasoning upserts cr_sessions by sessionId; on first create, status='active' and created_at/updated_at set; on subsequent calls, updated_at changes and iteration must be >= existing iteration (monotonic).
- All personas in the tool payload must exist (create if missing) in cr_personas for the given session_id; unique(session_id, persona.id) is enforced.
- activePersonaId must reference an existing cr_personas row with matching session_id and status='active'.
- nextPersonaId when provided must reference an existing cr_personas row with matching session_id and status='active'.
- Every contribution in the payload must map to a cr_contributions row for that session: personaId must exist in cr_personas for the same session, type must be one of the allowed enums, and confidence must be within [0,1].
- Contribution ordering within a session is deterministic: the service assigns/maintains sequence such that unique(session_id, sequence) holds; any referenceIds must point to contributions in the same session with lower sequence (no forward references).
- For each contribution.referenceIds entry, a cr_contribution_references row is created; duplicates are ignored/blocked by unique(from_contribution_id, to_contribution_id).
- Each disagreement positions[].personaId must exist in cr_personas for the same session; positions objects must contain non-empty position string and arguments array (can be empty only if explicitly allowed by implementation; otherwise length>=1).
- If a disagreement includes resolution, then status must be set to 'resolved' and both resolution.type and resolution.description must be non-null; if no resolution provided, status remains 'open'.
- When a session status transitions to 'completed', next_contribution_needed must be false and final_recommendation must be non-null; once archived, session becomes immutable except for updated_at and internal metadata migrations.