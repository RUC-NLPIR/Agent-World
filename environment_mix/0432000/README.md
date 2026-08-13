# SageTrail ML Workspace

SageTrail ML Workspace is a lightweight service for browsing ML projects and their associated artifacts and execution traces.

## Datastore

### `artifacts.json` — list of 50 records
Holds versioned artifact records and their metadata so the service can track produced assets per project and framework/model context.

- `artifact_id` — string
- `project_name` — string — one of data-preprocessing, gan-experiments, image-classification, nlp-sentiment, reinforcement-learning
- `name` — string
- `version` — string — one of v1, v2, v3, v4, v5
- `digest` — string
- `size_bytes` — integer
- `created_at` — string
- `metadata` — object
  each record in `metadata` has:
  - `framework` — string — one of jax, tensorflow, torch
  - `model_type` — string — one of bert, dqn, gpt, resnet, vae
  - `description` — string

### `projects.json` — list of 5 records
Holds project definitions and descriptive metadata so the service can organize artifacts and traces under named workspaces.

- `name` — string — one of data-preprocessing, gan-experiments, image-classification, nlp-sentiment, reinforcement-learning
- `entity` — string
- `description` — string
- `visibility` — string — one of private, public
- `created_at` — string
- `updated_at` — string
- `tags` — array

### `traces.json` — list of 227 records
Holds trace/span records with timing, status, and cost/attribute details so the service can inspect and analyze operational executions per project.
Lifecycle field `status`, states observed: error, success

- `id` — string
- `trace_id` — string
- `parent_id` — string — nullable
- `project_name` — string — one of data-preprocessing, gan-experiments, image-classification, nlp-sentiment, reinforcement-learning
- `op_name` — string
- `display_name` — string
- `started_at` — string
- `ended_at` — string
- `status` — string — one of error, success
- `latency_ms` — integer
- `costs` — object
  each record in `costs` has:
  - `prompt_tokens_total_cost` — number
  - `completion_tokens_total_cost` — number
  - `total_cost` — number
- `attributes` — object
  each record in `attributes` has:
  - `model_name` — string
  - `token_count` — integer

### `users.json` — list of 10 records
Holds user identities and basic profile metadata so the service can attribute activity and ownership across the other collections.

- `user_id` — string
- `username` — string
- `email` — string
- `entity` — string
- `created_at` — string
