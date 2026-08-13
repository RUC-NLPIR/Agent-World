# Decision Framework Server — local MCP environment

This backend stores structured decision-analysis workspaces where a single decision is iteratively refined across stages (problem definition → options → criteria → evaluation → analysis → recommendation). Each decision captures options, criteria and their evaluations, probabilistic outcomes, information gaps, and computed analysis artifacts (expected values, multi-criteria scores, sensitivity insights, recommendation) for a specified analysis type and risk tolerance.

Repository: https://github.com/waldzellai/model-enhancement-servers
Homepage: https://smithery.ai/server/@waldzellai/decision-framework

## Datastore

- `decisions.json` — Top-level decision records representing an iterative decision-analysis session for a given decisionId, including stage/iteration tracking and final computed artifacts. (18 rows; fields: ['id', 'decision_id', 'decision_statement', 'analysis_type', 'risk_tolerance', 'time_horizon', 'stage', 'iteration', 'next_stage_needed', 'suggested_next_stage', 'status', 'stakeholders', 'constraints_list', 'expected_values', 'multi_criteria_scores', 'sensitivity_insights', 'recommendation', 'created_at', 'updated_at'])
  - lifecycle `status`: ['draft', 'in_progress', 'finalized', 'archived']
  - constraint: unique(decision_id)
  - constraint: iteration >= 0
  - constraint: stage IN ('problem-definition','options','criteria','evaluation','analysis','recommendation')
  - constraint: analysis_type IN ('expected-utility','multi-criteria','maximin','minimax-regret','satisficing')
- `decision_options.json` — Options/alternatives belonging to a decision, with stable option ids used by evaluations and outcomes. (17 rows; fields: ['id', 'decision_id', 'option_key', 'name', 'description', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated']
  - constraint: foreign key(decision_id) references decisions(id) on delete cascade
  - constraint: unique(decision_id, option_key)
  - constraint: name is non-empty
  - constraint: description is non-empty
- `decision_criteria.json` — Evaluation criteria attached to a decision, including weight and evaluation method. (18 rows; fields: ['id', 'decision_id', 'criterion_key', 'name', 'description', 'weight', 'evaluation_method', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deprecated']
  - constraint: foreign key(decision_id) references decisions(id) on delete cascade
  - constraint: unique(decision_id, criterion_key)
  - constraint: weight >= 0 AND weight <= 1
  - constraint: evaluation_method IN ('quantitative','qualitative','boolean')
- `criteria_evaluations.json` — Join table scoring each option against each criterion with an auditable justification. (17 rows; fields: ['id', 'decision_id', 'criterion_id', 'option_id', 'score', 'justification', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded']
  - constraint: foreign key(decision_id) references decisions(id) on delete cascade
  - constraint: foreign key(criterion_id) references decision_criteria(id) on delete cascade
  - constraint: foreign key(option_id) references decision_options(id) on delete cascade
  - constraint: unique(decision_id, criterion_id, option_id) WHERE status = 'active'
- `decision_risk_items.json` — Stores uncertainty-related inputs: possible outcomes with probability/value/confidence and information gaps with impact/research method. (19 rows; fields: ['id', 'decision_id', 'item_type', 'client_item_key', 'option_id', 'description', 'probability', 'value', 'confidence_in_estimate', 'impact', 'research_method', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'resolved', 'deprecated']
  - constraint: foreign key(decision_id) references decisions(id) on delete cascade
  - constraint: foreign key(option_id) references decision_options(id) on delete cascade
  - constraint: item_type IN ('possible_outcome','information_gap')
  - constraint: item_type = 'possible_outcome' implies option_id IS NOT NULL AND probability IS NOT NULL AND value IS NOT NULL AND confidence_in_estimate IS NOT NULL AND impact IS NULL AND research_method IS NULL

## Business rules enforced by the tools

- Calling decisionFramework with a new decisionId creates a decisions row (status='draft') plus upserts for options, criteria, evaluations, outcomes, and information gaps keyed by (decision_id, option_key)/(decision_id, criterion_key) and applicable unique constraints.
- For a given decision, option keys and criterion keys must be unique within that decision; incoming options[].id / criteria[].id, when provided, must map consistently to the same stored rows across iterations.
- criteriaEvaluations[].criterionId and optionId refer to the client keys; the server must resolve them to decision_criteria.criterion_key and decision_options.option_key within the same decision_id, and reject any evaluation referencing unknown keys.
- For each decision, active criteria weights must satisfy: SUM(weight) <= 1.0 (if SUM(weight) > 1.0 the request is rejected); if analysis_type='multi-criteria' then SUM(weight) must be approximately 1.0 within tolerance 0.001 at stage >= 'analysis'.
- Scores, weights, probabilities, confidence_in_estimate, and impact must each be within [0,1]; values may be any finite number. Requests violating bounds are rejected.
- If analysis_type='expected-utility' and stage >= 'analysis', each active option must have at least one active possible_outcome; otherwise the decision cannot be finalized.
- If analysis_type='multi-criteria' and stage >= 'analysis', each active option must have an active criteria_evaluation for each active criterion; otherwise the decision cannot be finalized.
- When decisions.status transitions to 'finalized', the server must persist decisions.expected_values and/or decisions.multi_criteria_scores consistent with analysis_type, and must set decisions.recommendation to a non-empty string.
- Information gaps marked status='resolved' must have a non-empty research_method and an impact in [0,1]; resolving a gap does not delete it.
- Stage and iteration must be monotonically non-decreasing for a given decision_id unless the decision is archived; attempts to lower stage or iteration are rejected.