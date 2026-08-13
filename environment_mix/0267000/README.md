# Vibe-Coder — local MCP environment

Vibe-Coder stores iterative feature-planning workspaces where a user starts a feature clarification session, answers clarification questions, generates a PRD, and then executes the work via phases and tasks. It also tracks generated/saved documents (e.g., PRD) with paths so tools can resolve where artifacts live and update them over time.

Repository: https://github.com/crazyrabbitLTC/mcp-vibecoder
Homepage: https://smithery.ai/server/@crazyrabbitLTC/mcp-vibecoder

## Datastore

- `features.json` — Top-level feature planning/implementation unit. Created when clarification starts; later holds PRD generation state and overall workflow status. (18 rows; fields: ['id', 'feature_name', 'initial_description', 'status', 'active_phase_id', 'clarification_open_count', 'clarification_answered_count', 'prd_version', 'created_at', 'updated_at'])
  - lifecycle `status`: ['clarifying', 'prd_generated', 'planning', 'in_execution', 'completed', 'archived']
  - constraint: feature_name length between 2 and 100
  - constraint: clarification_open_count >= 0
  - constraint: clarification_answered_count >= 0
  - constraint: prd_version >= 0
- `clarifications.json` — Stores clarification Q&A pairs for a feature. Provides the persistence needed for provide_clarification and for PRD generation inputs. (19 rows; fields: ['id', 'feature_id', 'question', 'answer', 'status', 'asked_at', 'answered_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['open', 'answered', 'superseded']
  - constraint: question length >= 1
  - constraint: answer length >= 1 when status = 'answered'
  - constraint: answered_at is not null when status = 'answered'
  - constraint: unique(feature_id, question) to prevent accidental duplicate question strings
- `phases.json` — Execution plan phases for a feature. Supports create_phase, update_phase_status, and drives get_next_phase_action. (18 rows; fields: ['id', 'feature_id', 'name', 'description', 'sequence_index', 'status', 'started_at', 'completed_at', 'reviewed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'in_progress', 'completed', 'reviewed']
  - constraint: name length >= 1
  - constraint: description length >= 1
  - constraint: sequence_index >= 0
  - constraint: unique(feature_id, sequence_index)
- `tasks.json` — Concrete tasks within a phase. Supports add_task and update_task_status and is used by get_next_phase_action to compute next work item. (18 rows; fields: ['id', 'feature_id', 'phase_id', 'description', 'sequence_index', 'status', 'completed', 'completed_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['pending', 'completed']
  - constraint: description length >= 1
  - constraint: sequence_index >= 0
  - constraint: unique(phase_id, sequence_index)
  - constraint: completed = true implies status = 'completed' and completed_at is not null
- `documents.json` — Generated or saved artifacts for a feature (e.g., PRD). Supports get_document_path and save_document, and stores metadata for generated_prd outputs. (17 rows; fields: ['id', 'feature_id', 'document_type', 'status', 'file_path', 'content_sha256', 'version', 'source', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'generated', 'saved', 'archived']
  - constraint: document_type length >= 1
  - constraint: file_path length >= 1 when status in ('generated','saved')
  - constraint: version >= 1
  - constraint: unique(feature_id, document_type, version)

## Business rules enforced by the tools

- start_feature_clarification creates a features row with status='clarifying', clarification_open_count=0, clarification_answered_count=0, prd_version=0; feature_name must be 2..100 chars and initial_description may be empty string.
- provide_clarification upserts a clarifications row for (feature_id, question): if an open clarification exists, set answer, status='answered', answered_at=now(); if none exists, create it with status='answered'. It must also increment features.clarification_answered_count and decrement features.clarification_open_count only when an open item becomes answered.
- generate_prd requires the feature to exist. It increments features.prd_version by 1, sets features.status to at least 'prd_generated' (no downgrade), and creates a documents row with document_type='prd', source='generated', status='generated', version=features.prd_version, and a computed file_path (or null if generation failed and then status must remain unchanged).
- create_phase requires feature_id to exist. It assigns phases.sequence_index = max(sequence_index)+1 for that feature, inserts with status='pending', and if features.active_phase_id is null sets it to the new phase id. It may also promote features.status to 'planning' if currently earlier than planning.
- update_phase_status must validate that phaseId belongs to featureId (phases.feature_id = featureId). It must enforce allowed status transitions exactly as declared for phases.status and set started_at/completed_at/reviewed_at timestamps on first entry to those states.
- add_task must validate that phaseId belongs to featureId. It assigns tasks.sequence_index = max(sequence_index)+1 for that phase, inserts with completed=false, status='pending'.
- update_task_status must validate that taskId belongs to (featureId, phaseId) and enforce: completed=true -> status='completed' and set completed_at=now(); completed=false -> status='pending' and clear completed_at. Re-opening a task is allowed by lifecycle transitions.
- get_next_phase_action reads phases and tasks for the feature and returns the next actionable item using deterministic ordering: prefer the active_phase_id if its status is not reviewed; within a phase, return the first pending task by sequence_index; if none pending and phase is in_progress, suggest moving phase to completed; if phase completed, suggest moving to reviewed; if active phase reviewed, advance features.active_phase_id to next phase by sequence_index.
- get_document_path must return the latest non-archived documents.file_path for (feature_id, document_type) by highest version. If none exists or file_path is null, it must return a not-found/empty result rather than fabricating a path.
- save_document requires feature_id to exist; it creates a new documents version for (feature_id, document_type) with source='user_saved', status='saved', file_path as provided, version = (max(version)+1). If filePath is omitted by the tool call, the service must still be able to store/update a document; in that case it must keep file_path unchanged (application-level PATCH semantics) and only bump version when content changed.