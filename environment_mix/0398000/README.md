# Scientific Computation MCP Server — local MCP environment

This backend stores user-created tensors (NumPy-like arrays) in a session/workspace-scoped tensor store and records computational operations (linear algebra, vector ops, symbolic calculus, and plotting requests) performed against those tensors or symbolic expressions. The main workflows are: create/view/delete tensors, run an operation that reads tensors and produces a derived result (possibly persisted as a new tensor), and audit/log each tool invocation with inputs, outputs, and errors for debugging and quota enforcement.

Repository: https://github.com/Aman-Amith-Shastry/scientific_computation_mcp
Homepage: https://smithery.ai/server/@Aman-Amith-Shastry/scientific_computation_mcp

## Datastore

- `workspaces.json` — Tenant/session boundary for the in-memory tensor store semantics. A workspace owns tensors and operation logs and is the scope for uniqueness of tensor names and quotas. (12 rows; fields: ['id', 'display_name', 'status', 'tensor_count_limit', 'max_tensor_elements', 'max_tensor_bytes', 'ops_per_minute_limit', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'suspended', 'deleted']
  - constraint: unique(display_name)
  - constraint: tensor_count_limit >= 0
  - constraint: max_tensor_elements >= 1
  - constraint: max_tensor_bytes >= 1024
- `tensors.json` — Stored tensors (NumPy arrays) keyed by name within a workspace. Backing store for create_tensor, view_tensor, delete_tensor, and all matrix/vector operations. (18 rows; fields: ['id', 'workspace_id', 'name', 'status', 'dtype', 'rank', 'shape', 'element_count', 'values', 'content_hash', 'bytes_size', 'origin_operation_id', 'deleted_at', 'created_at', 'updated_at'])
  - lifecycle `status`: ['active', 'deleted']
  - constraint: unique(workspace_id, name) WHERE status = 'active'
  - constraint: rank >= 1
  - constraint: element_count >= 1
  - constraint: bytes_size >= 1
- `operations.json` — Audit log of every tool invocation (matrix ops, symbolic calculus, plotting, tensor CRUD). Stores validated inputs mapped 1:1 from tool parameters and captures outputs/errors for traceability and caching. (20 rows; fields: ['id', 'workspace_id', 'tool_name', 'status', 'requested_at', 'started_at', 'finished_at', 'duration_ms', 'name', 'name_a', 'name_b', 'shape', 'values', 'scale_factor', 'in_place', 'new_basis', 'new_vector', 'f_str', 'expr_str', 'point', 'is_vector', 'u', 'unit', 'bounds_raw', 'n', 'xlim', 'ylim', 'grid_raw', 'output_kind', 'result_tensor_id', 'result_payload', 'error_message', 'created_at', 'updated_at'])
  - lifecycle `status`: ['queued', 'running', 'succeeded', 'failed', 'cancelled']
  - constraint: finished_at IS NULL OR finished_at >= started_at
  - constraint: started_at IS NULL OR started_at >= requested_at
  - constraint: duration_ms IS NULL OR duration_ms >= 0
  - constraint: If tool_name in ('add_matrices','subtract_matrices','multiply_matrices','vector_dot_product','vector_cross_product') then name_a and name_b are required and name is NULL
- `operation_tensor_refs.json` — Normalized join table linking operations to the tensors they read and/or wrote. Used to enforce FK integrity and enable lineage queries (e.g., what tensors were inputs to an inverse). (18 rows; fields: ['id', 'operation_id', 'tensor_id', 'role', 'created_at', 'updated_at'])
  - lifecycle `role`: ['input_a', 'input_b', 'input', 'output']
  - constraint: unique(operation_id, tensor_id, role)
  - constraint: operation_id and tensor_id must belong to same workspace via operations.workspace_id = tensors.workspace_id
  - constraint: At most one role='output' per operation when operations.output_kind='tensor'
- `workspace_usage_counters.json` — Aggregated counters for quota and rate-limit enforcement per workspace and time window. Updated transactionally with operation creation/completion. (17 rows; fields: ['id', 'workspace_id', 'window_start', 'window_seconds', 'ops_requested', 'ops_succeeded', 'ops_failed', 'tensor_bytes_written', 'created_at', 'updated_at'])
  - lifecycle `window_seconds`: ['60']
  - constraint: unique(workspace_id, window_start, window_seconds)
  - constraint: window_seconds = 60
  - constraint: ops_requested >= 0
  - constraint: ops_succeeded >= 0

## Business rules enforced by the tools

- Tensor names are unique per workspace among active tensors; create_tensor with an existing active name must fail unless implemented as an explicit overwrite (not present in tool surface).
- create_tensor must validate that product(shape) equals len(values), each shape dimension is >= 1, and element_count <= workspaces.max_tensor_elements and bytes_size <= workspaces.max_tensor_bytes.
- delete_tensor performs a soft delete by setting tensors.status='deleted' and tensors.deleted_at; subsequent view_tensor and any operation referencing that name must behave as not found.
- All operations that accept name/name_a/name_b must resolve those names to active tensors within the same workspace before computation; otherwise the operation is recorded as failed with error_message.
- add_matrices/subtract_matrices require identical shapes; multiply_matrices requires 2D matrices with inner dimensions compatible; vector_dot_product requires same-length 1D vectors; vector_cross_product requires both vectors length 3.
- matrix_inverse and determinant require a 2D square matrix; matrix_inverse must fail if singular (non-invertible). compute_eigen requires a 2D square matrix.
- scale_matrix with in_place=true updates the existing tensor row (values/content_hash/updated_at) and records an operations row whose result_tensor_id equals the same tensor id; with in_place=false it returns a derived tensor result without mutating the original (may be persisted as a new tensor or stored only in result_payload depending on implementation).
- transpose returns a derived tensor (shape reversed for 2D; generalized transpose may be limited by implementation); determinant returns scalar output_kind='scalar'.
- qr_decompose/svd_decompose record output_kind='json' with result_payload containing matrices (q/r or u/s/vt) unless the system persists them as named tensors (not supported by tool parameters).
- find_orthonormal_basis returns output_kind='json' with result_payload as list of basis vectors; change_basis validates new_basis dimensions are square and invertible and compatible with the stored matrix.
- gradient/laplacian/directional_deriv return output_kind='text' (symbolic string); curl/divergence return output_kind='json' with keys including symbolic result and optionally numeric evaluation when point is provided.
- plot_vector_field and plot_function store the request parameters in operations and set output_kind='plot'; because the tool surface returns no image, result_payload may store rendering metadata only (e.g., backend='matplotlib', figure_id).
- For curl/divergence, if point is provided it must be length 3; for directional_deriv, u must be length 3 and if unit=true the backend normalizes u unless its norm is zero (then fail).
- Each tool invocation must create an operations row in status 'queued' then transition through 'running' to 'succeeded' or 'failed'; status transitions outside the declared graph are rejected.
- Workspace rate limiting: before starting an operation, increment workspace_usage_counters.ops_requested for the current minute bucket and reject if ops_requested would exceed workspaces.ops_per_minute_limit (unless limit=0 meaning unlimited).
- Workspace tensor-count quota: when creating a new active tensor, reject if active tensor count would exceed workspaces.tensor_count_limit (unless limit=0 meaning unlimited).
- FK integrity: operations.workspace_id must exist and be active; tensors.workspace_id must exist and be active; operation_tensor_refs must reference existing rows and must not link across workspaces.