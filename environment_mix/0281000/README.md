# Scientific Research Extension — local MCP environment

This backend stores scientific research analysis sessions as ASR-GoT graphs, including task initialization, dimension decomposition, hypothesis generation, and exportable summaries. It also stores resilient end-to-end query executions with stage-by-stage status, fallbacks, and final outputs, enabling summary and export tools to read consistent graph state.

Repository: https://github.com/SaptaDey/scientific-research-claude-extension
Homepage: https://smithery.ai/server/@SaptaDey/scientific-research-claude-extension

## Datastore

- `research_sessions.json` — Top-level container for a single research task/query. Holds configuration (P1.23 multi-layer, dimensions defaults, fallbacks), root metadata (P1.6), and overall lifecycle for the ASR-GoT graph. (19 rows; fields: ['id', 'task_description', 'initial_confidence', 'enable_multi_layer', 'enable_fallbacks', 'default_dimensions', 'disciplinary_tags', 'attribution', 'parameter_status', 'formalism_state', 'root_node_key', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['initialized', 'decomposed', 'hypotheses_generated', 'completed', 'failed', 'archived']
  - constraint: json_array_length(initial_confidence) = 4
  - constraint: forall v in initial_confidence: 0 <= v <= 1
  - constraint: root_node_key = 'n0'
  - constraint: json_array_length(default_dimensions) >= 2
- `graph_nodes.json` — All nodes in the ASR-GoT graph for a session (root, dimension nodes 2.X, hypothesis nodes, and other supporting nodes). Provides stable addressing for dimension_node_id and export/summary views. (18 rows; fields: ['id', 'session_id', 'node_key', 'node_type', 'label', 'content', 'layer', 'disciplinary_tags', 'attribution', 'metadata', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'superseded', 'deleted']
  - constraint: foreign key (session_id) references research_sessions(id) on delete cascade
  - constraint: unique(session_id, node_key)
  - constraint: node_type='root' implies node_key='n0' and label='Task Understanding'
  - constraint: node_type='dimension' implies node_key matches regex '^2\.[1-9][0-9]*$'
- `graph_edges.json` — Directed edges between graph nodes to represent decomposition, hypothesis generation relationships, and cross-links used for topology metrics (P1.22) and exports. (18 rows; fields: ['id', 'session_id', 'from_node_id', 'to_node_id', 'edge_type', 'weight', 'metadata', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: foreign key (session_id) references research_sessions(id) on delete cascade
  - constraint: foreign key (from_node_id) references graph_nodes(id) on delete cascade
  - constraint: foreign key (to_node_id) references graph_nodes(id) on delete cascade
  - constraint: from_node_id != to_node_id
- `hypotheses.json` — Normalized hypothesis details generated per dimension. Each hypothesis also corresponds to a graph_nodes row (node_type='hypothesis') for topology and export, but this table enforces P1.16/P1.28 and plan schema. (18 rows; fields: ['id', 'session_id', 'dimension_node_id', 'hypothesis_node_id', 'content', 'confidence', 'falsification_criteria', 'impact_score', 'disciplinary_tags', 'plan', 'attribution', 'status', 'created_at', 'updated_at'])
  - lifecycle `status`: ['proposed', 'accepted', 'rejected', 'superseded']
  - constraint: foreign key (session_id) references research_sessions(id) on delete cascade
  - constraint: dimension_node_id references graph_nodes(id) where graph_nodes.node_type='dimension'
  - constraint: hypothesis_node_id references graph_nodes(id) where graph_nodes.node_type='hypothesis'
  - constraint: graph_nodes.session_id for dimension_node_id and hypothesis_node_id must equal hypotheses.session_id
- `query_executions.json` — Tracks execute_resilient_query runs, including requested config overrides, per-stage outcomes, fallback usage, and linkage to the created/updated research session graph. (24 rows; fields: ['id', 'session_id', 'query', 'config_overrides', 'max_hypotheses', 'dimensions', 'initial_confidence', 'fallbacks_enabled', 'stages', 'result_summary', 'status', 'started_at', 'finished_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['running', 'succeeded', 'succeeded_with_fallbacks', 'failed', 'cancelled']
  - constraint: foreign key (session_id) references research_sessions(id) on delete restrict
  - constraint: max_hypotheses is null or (3 <= max_hypotheses and max_hypotheses <= 5)
  - constraint: initial_confidence is null or (json_array_length(initial_confidence)=4 and forall v in initial_confidence: 0<=v<=1)
  - constraint: if dimensions is not null then dimensions contains 'Potential Biases' and 'Knowledge Gaps'

## Business rules enforced by the tools

- initialize_asr_got_graph must create a research_sessions row with status='initialized', root_node_key='n0', and a graph_nodes root node (node_type='root', node_key='n0', label='Task Understanding') in the same session.
- decompose_research_task must create (or reactivate) dimension graph_nodes with node_type='dimension' and node_key values '2.1'..'2.N' in session order, and graph_edges from root to each dimension with edge_type='decomposes_to'.
- decompose_research_task must ensure the dimension labels include 'Potential Biases' and 'Knowledge Gaps' even when custom dimensions are supplied; otherwise the request is rejected.
- generate_hypotheses.dimension_node_id is interpreted as a node_key (format '2.X'); the implementation must resolve it to graph_nodes.id for the current active session and must reject if it does not exist or is not node_type='dimension'.
- generate_hypotheses must accept 3 to 5 hypotheses per call; additionally, the resolved max_hypotheses (from generate_hypotheses.config.max_hypotheses or session/query settings) must be <= 5 and cannot be exceeded.
- For each generated hypothesis, the system must create a graph_nodes row (node_type='hypothesis') plus a hypotheses row referencing both the dimension node and the hypothesis node, and create a graph_edges row from the dimension node to the hypothesis node with edge_type='generates'.
- Every hypothesis must have non-empty falsification_criteria (P1.16) and a non-null plan object containing at least plan.type and plan.description; otherwise it is rejected.
- get_graph_summary must compute summary from research_sessions + graph_nodes + graph_edges + hypotheses; when include_topology=true it must return metrics derived from graph_edges (e.g., node/edge counts, degree distribution) and store/refresh them in research_sessions.formalism_state or query_executions.result_summary if caching is enabled.
- export_graph_data must serialize the full session graph (nodes, edges, hypotheses) and include reasoning trace information when include_reasoning_trace=true by embedding graph_nodes.metadata and graph_edges.metadata; export format must be either 'json' or 'yaml'.
- execute_resilient_query must create a query_executions row with status='running', apply config overrides to create/update a research_sessions row, and progress stages in query_executions.stages; on completion it must set status to succeeded/succeeded_with_fallbacks/failed and set finished_at.
- If a session is status='archived', no tools may mutate its nodes/edges/hypotheses; only get_graph_summary and export_graph_data are permitted.